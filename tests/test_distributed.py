"""Real separate HTTP processes; no mocked inter-service transport."""
from contextlib import ExitStack
import os
from pathlib import Path
import socket
import subprocess
import sys
import time

import httpx

from blackout.db import Store
from blackout.lab import Lab, SCENARIOS
from blackout.transport import HTTPTransport


def free_port():
    with socket.socket() as sock:
        sock.bind(('127.0.0.1',0))
        return sock.getsockname()[1]


def test_separate_service_processes_recover_all_scenarios(tmp_path):
    ports={r:free_port() for r in ('orders','payments','inventory')}
    urls={r:f'http://127.0.0.1:{p}' for r,p in ports.items()}
    processes=[]
    logs=[]
    try:
        for role in ports:
            env={**os.environ,'BLACKOUT_ROLE':role,'BLACKOUT_DATA_DIR':str(tmp_path/role),
                 'PYTHONPATH':str(Path(__file__).resolve().parents[1]),
                 **{r.upper()+'_URL':u for r,u in urls.items()}}
            env.pop('OTEL_EXPORTER_OTLP_ENDPOINT',None)
            env.pop('BLACKOUT_INTERNAL_TOKEN',None)
            log=open(tmp_path/f'{role}.log','w+');logs.append(log)
            p=subprocess.Popen([sys.executable,'-m','blackout','serve','--port',str(ports[role])],env=env,stdout=log,stderr=log)
            processes.append(p)
        with httpx.Client(trust_env=False,timeout=1) as client:
            deadline=time.monotonic()+20
            while time.monotonic()<deadline:
                try:
                    if all(client.get(u+'/healthz').status_code==200 for u in urls.values()):break
                except httpx.HTTPError:pass
                time.sleep(.1)
            else:raise AssertionError('Services did not start')
        transport=HTTPTransport(urls)
        store=Store(tmp_path/'control.sqlite');lab=Lab(store,transport)
        try:
            for scenario in SCENARIOS:
                run=store.create_run(scenario,'runbook')
                report=lab.run(run,scenario)
                assert report['status']=='recovered'
                assert report['after']['verification']['stock']==17
                assert not report['before']['verification']['healthy']
                spans=[e for e in report['after']['events'] if e['kind']=='span']
                assert spans and all(e['data']['otel_trace_id']!='0'*32 for e in spans)
        finally:transport.close()
    finally:
        for p in processes:p.terminate()
        for p in processes:
            try:p.wait(timeout=5)
            except subprocess.TimeoutExpired:p.kill();p.wait()
        for log in logs:log.close()
