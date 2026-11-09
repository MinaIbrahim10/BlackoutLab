from concurrent.futures import ThreadPoolExecutor
from pathlib import Path
import json
import time
import uuid

import httpx
import pytest
from fastapi.testclient import TestClient
from pydantic import ValidationError

from blackout.agents import AgentAnswer, OllamaAgents
from blackout.api import create_app
from blackout.db import Store
from blackout.lab import Lab, SCENARIOS
from blackout.services import DomainError, UNIT_PRICE
from blackout.transport import LocalTransport
from blackout.verify import snapshot, verify


@pytest.fixture
def system(tmp_path):
    store=Store(tmp_path/'control.sqlite')
    transport=LocalTransport(tmp_path)
    lab=Lab(store,transport)
    yield store,transport,lab
    transport.close()


def checkout(transport,run,key='test-001',qty=2):
    return transport.call('orders','checkout',run,{'key':key,'qty':qty,'amount':qty*UNIT_PRICE})


@pytest.mark.parametrize('scenario',SCENARIOS)
def test_each_fault_breaks_invariants_and_runbook_repairs_actual_state(system,scenario):
    store,transport,lab=system
    run=store.create_run(scenario,'runbook')
    report=lab.run(run,scenario)
    assert not report['before']['verification']['healthy']
    assert report['after']['verification']['healthy']
    assert report['status']=='recovered'
    assert report['after']['verification']['stock']==17
    assert report['after']['verification']['orders']==2
    assert report['after']['verification']['payments']==2
    assert store.get_run(run)['status']=='recovered'
    assert report['metrics']['agent_calls']==0


def test_checkout_replay_does_not_double_charge_or_reserve(system):
    store,transport,lab=system
    run=uuid.uuid4().hex
    for _ in range(8): checkout(transport,run)
    state=snapshot(transport,run)
    assert len(state['payments']['payments'])==1
    assert len(state['inventory']['reservations'])==1
    assert verify(state)['healthy']
    assert verify(state)['stock']==18


def test_concurrent_replays_converge(system):
    store,transport,lab=system
    run=uuid.uuid4().hex
    with ThreadPoolExecutor(max_workers=6) as pool:
        list(pool.map(lambda _:checkout(transport,run),range(12)))
    state=snapshot(transport,run)
    assert verify(state)['healthy']
    assert len(state['payments']['payments'])==len(state['orders']['orders'])==1


def test_conflicting_key_payload_is_rejected_before_new_side_effect(system):
    store,transport,lab=system
    run=uuid.uuid4().hex
    checkout(transport,run)
    with pytest.raises(DomainError): checkout(transport,run,qty=3)
    assert verify(snapshot(transport,run))['stock']==18


def test_recovery_actions_are_repeatable(system):
    store,transport,lab=system
    run=uuid.uuid4().hex
    lab.inject(run,'duplicate-reservation')
    for _ in range(3):
        lab.apply(run,'restore-inventory');lab.apply(run,'deduplicate-inventory')
    assert verify(snapshot(transport,run))['healthy']
    assert verify(snapshot(transport,run))['stock']==17


def test_run_namespaces_are_isolated(system):
    store,transport,lab=system
    first,second=uuid.uuid4().hex,uuid.uuid4().hex
    lab.inject(first,'orphaned-payment')
    checkout(transport,second)
    assert not verify(snapshot(transport,first))['healthy']
    assert verify(snapshot(transport,second))['healthy']
    assert len(snapshot(transport,second)['payments']['payments'])==1


def test_arbitrary_actions_and_invalid_faults_are_rejected(system):
    store,transport,lab=system
    with pytest.raises(ValueError):lab.apply(uuid.uuid4().hex,'rm -rf /')
    with pytest.raises(DomainError):transport.call('payments','fault',uuid.uuid4().hex,{'name':'drop-order','enabled':True})
    with pytest.raises(DomainError):transport.call('payments','fault',uuid.uuid4().hex,{'name':'payments-down','enabled':'false'})


def test_inference_failure_is_visible_and_does_not_trigger_runbook(system):
    store,transport,lab=system
    class Broken:
        model='test-unavailable'
        def ask(self,*args): raise TimeoutError()
    lab.agents=Broken()
    run=store.create_run('orphaned-payment','multi')
    report=lab.run(run,'orphaned-payment','multi')
    assert report['status']=='unresolved'
    assert report['actions']==[]
    assert report['metrics']['agent_failures']==1
    assert any(e['kind']=='agent.failed' for e in store.events(run))


def test_multi_agent_plan_executes_and_verifier_cannot_override_evidence(system):
    store,transport,lab=system
    class Fake:
        model='test-only'
        def __init__(self):self.calls=[]
        def ask(self,role,context):
            self.calls.append((role,context))
            return {'summary':'test answer','hypothesis':'writer failure','evidence':['capture exists'],
                    'actions':['restore-orders','replay-checkouts'] if role=='recovery' else []}
    fake=Fake();lab.agents=fake
    run=store.create_run('orphaned-payment','multi')
    report=lab.run(run,'orphaned-payment','multi')
    assert report['status']=='recovered'
    assert [r for r,c in fake.calls]==['commander','observer','investigator','recovery','verifier']
    assert len(fake.calls[3][1]['hearing'])==3
    assert all('actions' not in entry for entry in fake.calls[3][1]['hearing'])
    assert all(entry['evidence']==['capture exists'] for entry in fake.calls[3][1]['hearing'])
    assert 'faults' not in fake.calls[0][1]['state']['orders']
    assert report['metrics']['agent_calls']==5


def test_empty_ai_plan_cannot_self_declare_recovery(system):
    store,transport,lab=system
    class Wrong:
        model='test-only'
        def ask(self,*args):return {'summary':'Everything is fixed!','hypothesis':'','evidence':[],'actions':[]}
    lab.agents=Wrong()
    run=store.create_run('payments-outage','multi')
    report=lab.run(run,'payments-outage','multi')
    assert report['status']=='unresolved'
    assert not report['after']['verification']['healthy']


@pytest.mark.parametrize('mode',['single','multi'])
def test_measured_feedback_repairs_incomplete_plan_without_reference_fallback(system,mode):
    store,transport,lab=system
    class FeedbackAgent:
        model='test-only'
        def __init__(self): self.plans=[]
        def ask(self,role,context):
            actions=[]
            if role in ('single','recovery'):
                self.plans.append(context)
                actions=['restore-orders'] if len(self.plans)==1 else ['replay-checkouts']
            return {'summary':'Measured feedback response','actions':actions}
    agent=FeedbackAgent();lab.agents=agent
    run=store.create_run('orphaned-payment',mode)
    report=lab.run(run,'orphaned-payment',mode)
    assert report['status']=='recovered'
    assert len(agent.plans)==2
    feedback=agent.plans[1]
    assert feedback['remaining_rounds']==2
    assert not feedback['verification']['healthy']
    assert feedback['state']['orders']['orders']==[]
    assert all('faults' not in service for service in feedback['state'].values())
    assert 'scenario' not in feedback and 'runbook' not in feedback
    assert feedback['previous_attempts'][0]['plan']==['restore-orders']
    assert [r['plan'] for r in report['recovery_rounds']]==[['restore-orders'],['replay-checkouts']]
    assert report['metrics']['recovery_rounds']==2
    assert report['after']['verification']['payments']==2
    assert report['after']['verification']['stock']==17
    assert [a['action'] for a in report['actions']]==['restore-orders','replay-checkouts']


def test_repeated_wrong_plans_stop_at_budget_without_fallback(system):
    store,transport,lab=system
    class WrongAgent:
        model='test-only'
        def __init__(self):self.calls=0
        def ask(self,role,context):
            self.calls+=1
            return {'summary':'Incorrect plan','actions':[]}
    agent=WrongAgent();lab.agents=agent
    run=store.create_run('orphaned-payment','single')
    report=lab.run(run,'orphaned-payment','single')
    assert report['status']=='unresolved'
    assert agent.calls==3
    assert report['metrics']['recovery_rounds']==3
    assert report['actions']==[]
    assert not any(event['kind']=='runbook.selected' for event in store.events(run))


def test_feedback_inference_failure_preserves_measured_state_and_stops(system):
    store,transport,lab=system
    class FailsOnRetry:
        model='test-only'
        def __init__(self):self.calls=0
        def ask(self,role,context):
            self.calls+=1
            if self.calls>1: raise TimeoutError()
            return {'summary':'Incomplete plan','actions':['restore-orders']}
    agent=FailsOnRetry();lab.agents=agent
    run=store.create_run('orphaned-payment','single')
    report=lab.run(run,'orphaned-payment','single')
    assert report['status']=='unresolved'
    assert agent.calls==2
    assert report['metrics']['agent_failures']==1
    assert report['metrics']['recovery_rounds']==1
    assert report['after']['state']['orders']['faults']['drop-order'] is False
    assert report['after']['verification']['orders']==0


def test_invalid_round_budget_is_rejected(system):
    store,transport,_=system
    for budget in [0,4,True,'3']:
        with pytest.raises(ValueError): Lab(store,transport,max_rounds=budget)


def test_agent_schema_rejects_shell_commands():
    with pytest.raises(ValidationError):AgentAnswer(summary='bad',actions=['curl evil'])
    with pytest.raises(ValidationError):AgentAnswer(summary='bad',unexpected='field')


def test_ollama_adapter_checks_response_and_analysis_role_permissions(monkeypatch):
    payloads=[]
    answer={'summary':'diagnosis','evidence':['orders.checkout failed after capture'],'actions':['restore-orders']}
    class Response:
        def raise_for_status(self):pass
        def json(self):return {'message':{'content':json.dumps(answer)}}
    class Client:
        def __init__(self,**kwargs):pass
        def __enter__(self):return self
        def __exit__(self,*args):pass
        def post(self,url,json):payloads.append(json);return Response()
    monkeypatch.setattr('blackout.agents.httpx.Client',Client)
    agent=OllamaAgents(model='test-only')
    with pytest.raises(ValueError):agent.ask('observer',{})
    assert agent.ask('recovery',{})['actions']==['restore-orders']
    assert payloads[0]['format']['properties']['actions']['items']['enum']
    assert payloads[0]['stream'] is False
    assert payloads[0]['think'] is False
    assert payloads[0]['format']['properties']['actions']['maxItems'] == 0
    assert payloads[1]['format']['properties']['actions']['maxItems'] == 5
    assert payloads[1]['format']['properties']['evidence']['minItems'] == 1
    assert 'evidence' in payloads[1]['format']['required']
    assert payloads[1]['format']['properties']['actions']['minItems'] == 1
    answer['evidence']=[]
    with pytest.raises(ValueError,match='cite observed evidence'):agent.ask('recovery',{})
    answer['evidence']=['observed failure'];answer['actions']=[]
    with pytest.raises(ValueError,match='no executable actions'):agent.ask('recovery',{})


def test_corrupted_payment_quantity_fails_verifier(system):
    store,transport,lab=system
    run=uuid.uuid4().hex;checkout(transport,run)
    state=snapshot(transport,run);state['payments']['payments'][0]['qty']=4
    assert not verify(state)['healthy']


def test_api_background_run_and_download(tmp_path):
    app=create_app(tmp_path)
    with TestClient(app) as client:
        response=client.post('/api/runs',json={'scenario':'orphaned-payment','mode':'runbook'})
        assert response.status_code==202
        run=response.json()['id']
        for _ in range(100):
            data=client.get('/api/runs/'+run).json()
            if data['status'] in ('recovered','failed'):break
            time.sleep(.02)
        assert data['status']=='recovered'
        assert client.get(f'/api/runs/{run}/state').json()['verification']['healthy']
        events=client.get(f'/api/runs/{run}/events').json()
        assert events[-1]['kind']=='run.completed'
        assert client.get(f'/api/runs/{run}/events?after={events[-1]["seq"]}').json()==[]
        report=client.get(f'/api/runs/{run}/report')
        assert report.status_code==200 and 'attachment' in report.headers['content-disposition']
        assert report.json()['metrics']['checks_passed']==6
        assert client.get('/').status_code==200
        assert client.get('/static/app.js').status_code==200
        assert "script-src 'self'" in client.get('/').headers['content-security-policy']


def test_api_rejects_invalid_inputs_and_cross_origin(tmp_path):
    with TestClient(create_app(tmp_path)) as client:
        assert client.post('/api/runs',json={'scenario':'unknown'}).status_code==422
        assert client.post('/api/runs',json={'scenario':'orphaned-payment','mode':'shell'}).status_code==422
        assert client.post('/api/runs',json={'scenario':'orphaned-payment'},headers={'Origin':'https://evil.example'}).status_code==403
        assert client.get('/api/runs/not-a-run').status_code==404
        assert client.get('/api/runs/'+'f'*32).status_code==404
        assert client.get('/healthz',headers={'Host':'evil.example'}).status_code==400


def test_startup_marks_unfinished_runs_interrupted(tmp_path):
    app=create_app(tmp_path)
    run=app.state.store.create_run('orphaned-payment','multi')
    with TestClient(app) as client:
        assert client.get('/api/runs/'+run).json()['status']=='interrupted'


def test_internal_token_and_validation(tmp_path,monkeypatch):
    monkeypatch.setenv('BLACKOUT_INTERNAL_TOKEN','test-token-only')
    with TestClient(create_app(tmp_path,role='payments')) as client:
        path='/internal/'+'a'*32+'/capture'
        assert client.post(path,json={}).status_code==403
        assert client.post(path,json={},headers={'X-Lab-Token':'test-token-only'}).status_code==422
        assert client.post('/internal/invalid/snapshot',json={},headers={'X-Lab-Token':'test-token-only'}).status_code==422
        assert client.post(path,json={'key':'test','qty':1,'amount':2500},headers={'X-Lab-Token':'test-token-only'}).status_code==200


def test_planner_receives_observed_dependency_failure_without_fault_switches(system):
    store,transport,_=system
    class RecordingAgent:
        context=None
        def ask(self,role,context):
            self.context=context
            return {'summary':'No plan','actions':[]}
    agent=RecordingAgent()
    lab=Lab(store,transport,agent,max_rounds=1)
    rid=store.create_run('payments-outage','single')
    report=lab.run(rid,'payments-outage','single')
    errors=agent.context['observed_operation_failures']
    assert any(e['service']=='payments' and e['operation']=='capture' and 'unavailable' in e['error'] for e in errors)
    assert len(errors)==len({json.dumps(e,sort_keys=True) for e in errors})
    assert all(set(e)=={'service','operation','error'} for e in errors)
    assert all('faults' not in service for service in agent.context['state'].values())
    assert 'scenario' not in agent.context and 'runbook' not in agent.context
    assert report['status']=='unresolved' and report['actions']==[]


def test_invalid_response_gets_one_correction_before_any_action(system):
    store,transport,lab=system
    class Corrected:
        model='test-only'
        def __init__(self):self.calls=0
        def ask(self,role,context):
            self.calls+=1
            if self.calls==1:raise ValueError('Invalid structured response')
            assert context['response_validation_feedback']['error_type']=='ValueError'
            assert not verify(snapshot(transport,rid))['healthy']
            assert not any(e['kind']=='action.started' for e in store.events(rid))
            return {'summary':'Validated repair','actions':['restore-payments','replay-checkouts']}
    agent=Corrected();lab.agents=agent
    rid=store.create_run('payments-outage','single')
    report=lab.run(rid,'payments-outage','single')
    assert report['status']=='recovered' and agent.calls==2
    assert [c['status'] for c in report['agents']]==['failed','completed']
    assert report['agents'][0]['will_retry'] is True
    assert report['metrics']['agent_calls']==2
    assert report['metrics']['agent_failures']==1
    assert report['metrics']['response_retries']==1
    assert report['metrics']['actions_attempted']==2
    assert not any(e['kind']=='runbook.selected' for e in store.events(rid))


def test_invalid_response_correction_budget_stops_without_fallback(system):
    store,transport,lab=system
    class Invalid:
        def ask(self,*args):raise ValueError('Always invalid')
    lab.agents=Invalid()
    rid=store.create_run('payments-outage','single')
    report=lab.run(rid,'payments-outage','single')
    assert report['status']=='unresolved' and report['actions']==[]
    assert report['metrics']['agent_calls']==2
    assert report['metrics']['agent_failures']==2
    assert report['metrics']['response_retries']==1
    assert report['agents'][-1]['will_retry'] is False
