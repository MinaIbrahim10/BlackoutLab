from concurrent.futures import ThreadPoolExecutor
from contextlib import asynccontextmanager
from pathlib import Path
from threading import BoundedSemaphore
from typing import Literal
import os
import re
import secrets
from urllib.parse import urlsplit

from fastapi import FastAPI, HTTPException, Request
from fastapi.responses import FileResponse, JSONResponse
from fastapi.staticfiles import StaticFiles
from pydantic import BaseModel, ConfigDict
from starlette.middleware.trustedhost import TrustedHostMiddleware
from opentelemetry.context import attach, detach
from opentelemetry.propagate import extract

from .agents import OllamaAgents
from .db import Store
from .lab import Lab, SCENARIOS
from .services import Service, DomainError
from .transport import LocalTransport, HTTPTransport
from .verify import snapshot, verify

RUN_ID = re.compile(r'^[a-f0-9]{32}$')


class RunRequest(BaseModel):
    model_config = ConfigDict(extra='forbid')
    scenario: Literal['orphaned-payment','duplicate-reservation','payments-outage']
    mode: Literal['runbook','multi','single'] = 'runbook'


def create_app(data_dir=None, role=None, agents=None, transport=None):
    role = role or os.getenv('BLACKOUT_ROLE','all')
    if role not in ('all','control','orders','payments','inventory'):
        raise ValueError('Invalid service role')
    root = Path(data_dir or os.getenv('BLACKOUT_DATA_DIR','./data'))
    root.mkdir(parents=True,exist_ok=True)
    control = role in ('all','control')
    store = Store(root / f'{role}.sqlite')
    transport = transport or (LocalTransport(root) if role=='all' else HTTPTransport() if role in ('control','orders') else None)
    service = None if control else Service(role,store,transport)
    executor = ThreadPoolExecutor(max_workers=2,thread_name_prefix='blackout') if control else None
    slots = BoundedSemaphore(4)
    lab = Lab(store,transport,agents or OllamaAgents()) if control else None

    @asynccontextmanager
    async def lifespan(app):
        if control:
            # A single control worker owns the persisted run lifecycle.
            for run in store.runs():
                if run['status'] not in ('recovered','unresolved','failed','interrupted'):
                    store.update_run(run['id'],'interrupted',{'error':'Control service restarted before completion.'})
        yield
        if executor: executor.shutdown(wait=True,cancel_futures=False)
        if transport: transport.close()
        if service: service.provider.shutdown()

    app = FastAPI(title='Blackout Lab',version='0.1.0',lifespan=lifespan)
    allowed_hosts = os.getenv('BLACKOUT_ALLOWED_HOSTS','localhost,127.0.0.1,testserver,control,orders,payments,inventory').split(',')
    app.add_middleware(TrustedHostMiddleware,allowed_hosts=allowed_hosts)
    app.state.store,app.state.lab,app.state.transport = store,lab,transport

    @app.middleware('http')
    async def boundary(request,call_next):
        if request.method not in ('GET','HEAD','OPTIONS'):
            origin = request.headers.get('origin')
            if origin and urlsplit(origin).netloc != request.headers.get('host'):
                return JSONResponse({'detail':'Cross-origin writes are not allowed'},status_code=403)
        response = await call_next(request)
        response.headers['X-Content-Type-Options'] = 'nosniff'
        response.headers['Referrer-Policy'] = 'no-referrer'
        response.headers['Content-Security-Policy'] = "default-src 'self'; script-src 'self'; style-src 'self'; connect-src 'self'; img-src 'self' data:; frame-ancestors 'none'; base-uri 'none'"
        return response

    @app.exception_handler(DomainError)
    async def domain_error(request,exc): return JSONResponse({'detail':str(exc)},status_code=exc.status)

    @app.get('/healthz')
    def health(): return {'status':'ok','role':role}

    if not control:
        @app.post('/internal/{run}/{action}')
        def internal(run: str, action: str, payload: dict, request: Request):
            if not RUN_ID.fullmatch(run): raise HTTPException(422,'Invalid run ID')
            token = os.getenv('BLACKOUT_INTERNAL_TOKEN')
            if token and not secrets.compare_digest(request.headers.get('X-Lab-Token',''),token):
                raise HTTPException(403,'Internal token required')
            context = attach(extract(dict(request.headers)))
            try:
                return service.call(action,run,payload,request.headers.get('X-Lab-Correlation'))
            except (KeyError,TypeError,ValueError) as exc:
                raise HTTPException(422,'Invalid operation payload') from exc
            finally: detach(context)
        return app

    def require_run(run):
        if not RUN_ID.fullmatch(run): raise HTTPException(404,'Run not found')
        result = store.get_run(run)
        if not result: raise HTTPException(404,'Run not found')
        return result

    @app.get('/api/scenarios')
    def scenarios():
        return [{k:v for k,v in {'id':key,**value}.items() if k not in ('fault','runbook')} for key,value in SCENARIOS.items()]

    @app.get('/api/config')
    def config():
        return {'default_mode':'runbook','model':lab.agents.model,'deployment':'distributed-http' if role=='control' else 'single-process',
                'max_recovery_rounds':lab.max_rounds,
                'scope':'Toy services only. No real payments or production infrastructure.'}

    @app.get('/api/runs')
    def runs(): return store.runs()

    def execute(run,scenario,mode):
        try: lab.run(run,scenario,mode)
        except Exception as exc:
            store.log(run,'control','run.failed',{'error':type(exc).__name__,'detail':str(exc)})
            store.update_run(run,'failed',{'error':type(exc).__name__,'detail':str(exc)})
        finally: slots.release()

    @app.post('/api/runs',status_code=202)
    def start(body: RunRequest):
        if not slots.acquire(blocking=False): raise HTTPException(429,'Run queue is full; wait for a current run to complete')
        try:
            run = store.create_run(body.scenario,body.mode)
            executor.submit(execute,run,body.scenario,body.mode)
        except BaseException:
            slots.release()
            raise
        return {'id':run,'status':'queued'}

    @app.get('/api/runs/{run}')
    def get_run(run: str): return require_run(run)

    @app.get('/api/runs/{run}/events')
    def get_events(run: str, after: int = 0):
        require_run(run)
        return store.events(run,max(after,0))

    @app.get('/api/runs/{run}/state')
    def get_state(run: str):
        require_run(run)
        state = snapshot(transport,run)
        return {'services':state,'verification':verify(state)}

    @app.get('/api/runs/{run}/report')
    def report(run: str):
        result = require_run(run)
        if result['status'] not in ('recovered','unresolved','failed','interrupted'):
            raise HTTPException(409,'Report is not complete')
        return JSONResponse(result['report'],headers={'Content-Disposition':f'attachment; filename="blackout-{run}.json"'})

    static = Path(__file__).parent / 'static'
    app.mount('/static',StaticFiles(directory=static),name='static')
    @app.get('/')
    def index(): return FileResponse(static/'index.html')
    return app
