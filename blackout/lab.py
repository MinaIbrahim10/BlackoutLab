"""Incident lifecycle, evidence collection, allowlisted recovery and truthful reports."""
import json
import time
from .agents import ACTIONS
from .services import DomainError, UNIT_PRICE
from .verify import snapshot, verify

SCENARIOS = {
    'orphaned-payment': {'title':'The missing order','severity':'SEV 1','fault':'drop-order','service':'orders',
        'description':'A payment is captured, but the order writer fails before inventory reservation and order commit.',
        'runbook':['restore-orders','replay-checkouts']},
    'duplicate-reservation': {'title':'Inventory déjà vu','severity':'SEV 2','fault':'duplicate-reservation','service':'inventory',
        'description':'A duplicate delivery bypasses reservation idempotency and consumes stock twice.',
        'runbook':['restore-inventory','deduplicate-inventory']},
    'payments-outage': {'title':'Payment blackout','severity':'SEV 1','fault':'payments-down','service':'payments',
        'description':'The payment endpoint rejects capture; durable checkout intents wait for recovery.',
        'runbook':['restore-payments','replay-checkouts']},
}


class Lab:
    def __init__(self, store, transport, agents=None, max_rounds=3):
        if type(max_rounds) is not int or not 1 <= max_rounds <= 3:
            raise ValueError('Recovery rounds must be between 1 and 3')
        self.store, self.transport, self.agents = store, transport, agents
        self.max_rounds = max_rounds

    def emit(self, run, kind, data, role='control'):
        self.store.log(run,role,kind,data)

    def collect(self, run):
        state = snapshot(self.transport,run)
        events = []
        for role in ('orders','payments','inventory'):
            events.extend(self.transport.call(role,'events',run))
        return {'state':state,'verification':verify(state),'events':sorted(events,key=lambda e:(e['at'],e['service'],e['seq']))[-60:]}

    def inject(self, run, scenario):
        spec = SCENARIOS[scenario]
        self.transport.call(spec['service'],'fault',run,{'name':spec['fault'],'enabled':True})
        self.emit(run,'chaos.injected',{'target':spec['service'],'fault':spec['fault']})
        for key,qty in [('checkout-001',2),('checkout-002',1)]:
            try:
                self.transport.call('orders','checkout',run,{'key':key,'qty':qty,'amount':qty*UNIT_PRICE},run)
            except DomainError as exc:
                self.emit(run,'traffic.failed',{'key':key,'status':exc.status,'detail':str(exc)},'orders')
        if scenario == 'duplicate-reservation':
            # Deliberately redeliver the inventory message to expose a missing deduplication guard.
            self.transport.call('inventory','reserve',run,{'key':'checkout-001','qty':2},run)

    def apply(self, run, action):
        if action not in ACTIONS:
            raise ValueError('Recovery action is not allowlisted')
        mapping = {'restore-orders':('orders','drop-order'), 'restore-payments':('payments','payments-down'),
                   'restore-inventory':('inventory','duplicate-reservation')}
        if action in mapping:
            role,name = mapping[action]
            result = self.transport.call(role,'fault',run,{'name':name,'enabled':False},run)
        elif action == 'replay-checkouts':
            result = self.transport.call('orders','retry-pending',run,correlation=run)
        else:
            result = self.transport.call('inventory','deduplicate',run,correlation=run)
        self.emit(run,'action.completed',{'action':action,'result':result},'recovery')
        return result

    def run(self, run, scenario, mode='runbook'):
        if scenario not in SCENARIOS or mode not in ('runbook','multi','single'):
            raise ValueError('Invalid scenario or mode')
        started = time.perf_counter()
        self.store.update_run(run,'injecting')
        self.emit(run,'run.started',{'scenario':scenario,'mode':mode})
        self.inject(run,scenario)
        before = self.collect(run)
        self.emit(run,'verification.before',before['verification'],'verifier')
        self.store.update_run(run,'investigating')
        calls = []
        failures = []
        actions = []
        rounds = []
        # Hide the scenario/runbook and injected fault configuration from the agent inputs.
        # Logs still expose authored failure messages: this is an introductory benchmark.
        def evidence(context):
            clean = json.loads(json.dumps(context))
            for s in clean.get('state',{}).values(): s.pop('faults',None)
            clean['events'] = [e for e in clean.get('events',[]) if e['kind'] != 'fault.changed']
            # Put observed leaf-operation failures before downstream ledger symptoms.
            # This is a projection of telemetry, not a scenario lookup or repair plan.
            failed = []
            for event in reversed(clean['events']):
                data = event.get('data', {})
                if data.get('status') != 'error' or not data.get('error'):
                    continue
                item = {'service':event['service'], 'operation':data.get('operation'),
                        'error':data['error']}
                if item not in failed:
                    failed.append(item)
            return {'observed_operation_failures':failed[:12], **clean}
        def ask(role, context):
            at = time.perf_counter()
            self.emit(run,'agent.started',{'role':role},role)
            try:
                if self.agents is None: raise RuntimeError('Ollama client is not configured')
                answer = self.agents.ask(role,context)
                calls.append({'role':role,'status':'completed','duration_ms':round((time.perf_counter()-at)*1000,2),**answer})
                self.emit(run,'agent.completed',calls[-1],role)
                return answer
            except Exception as exc:
                item = {'role':role,'status':'failed','error':type(exc).__name__,
                        'summary':'Agent inference failed. See Ollama configuration and server availability.',
                        'duration_ms':round((time.perf_counter()-at)*1000,2)}
                calls.append(item);failures.append(item)
                self.emit(run,'agent.failed',item,role)
                return None
        hearing = []
        if mode == 'runbook':
            plan = SCENARIOS[scenario]['runbook']
            self.emit(run,'runbook.selected',{'actions':plan,'note':'Deterministic reference baseline; no AI calls.'},'commander')
        else:
            context = evidence(before)
            if mode == 'multi':
                for role in ('commander','observer','investigator'):
                    answer = ask(role,{**context,'hearing':hearing})
                    if answer is None: break
                    hearing.append({'role':role, **{key:value for key,value in answer.items() if key != 'actions'}})
                proposed = None if failures else ask('recovery',{**context,'hearing':hearing})
            else:
                proposed = ask('single',context)
            plan = proposed.get('actions',[]) if proposed else []
        budget = 1 if mode == 'runbook' else self.max_rounds
        for round_number in range(1, budget + 1):
            self.store.update_run(run,'recovering')
            self.emit(run,'recovery.round',{'round':round_number,'budget':budget,'actions':plan},'recovery')
            round_actions = []
            for action in plan:
                try:
                    self.emit(run,'action.started',{'action':action,'round':round_number},'recovery')
                    result = self.apply(run,action)
                    item = {'action':action,'status':'completed','result':result}
                except Exception as exc:
                    item = {'action':action,'status':'failed','error':str(exc)}
                    self.emit(run,'action.failed',item,'recovery')
                actions.append(item)
                round_actions.append(item)
            self.store.update_run(run,'verifying')
            after = self.collect(run)
            self.emit(run,'verification.after',after['verification'],'verifier')
            rounds.append({'round':round_number,'plan':list(plan),'actions':round_actions,
                           'verification':after['verification']})
            if after['verification']['healthy'] or failures or round_number == budget:
                break
            # The model receives measured feedback, never the scenario's reference plan.
            feedback = evidence({**after,'previous_attempts':rounds,
                                 'remaining_rounds':budget-round_number})
            if mode == 'multi': feedback['hearing'] = hearing
            self.store.update_run(run,'investigating')
            proposed = ask('recovery' if mode == 'multi' else 'single',feedback)
            if proposed is None:
                break
            plan = proposed.get('actions',[])
        if mode == 'multi' and not failures:
            ask('verifier',{'verification':after['verification'],'actions':actions})
        healthy = after['verification']['healthy']
        status = 'recovered' if healthy else 'unresolved'
        report = {'run_id':run,'scenario':scenario,'mode':mode,'status':status,
                  'model':getattr(self.agents,'model',None) if mode!='runbook' else None,
                  'before':before,'after':after,'agents':calls,'actions':actions,'recovery_rounds':rounds,
                  'metrics':{'duration_ms':round((time.perf_counter()-started)*1000,2),
                             'agent_calls':len(calls),'agent_failures':len(failures),
                             'recovery_rounds':len(rounds),'max_recovery_rounds':budget,
                             'actions_attempted':len(actions),'actions_failed':sum(a['status']=='failed' for a in actions),
                             'checks_passed':sum(c['passed'] for c in after['verification']['checks']),
                             'checks_total':len(after['verification']['checks'])},
                  'limitations':['Only authored toy-service faults are supported. No production recovery claim.',
                                 'Fault labels are hidden from agent snapshots, but authored error messages can reveal the failure boundary.',
                                 'Recovery is based on accounting checks, never model self-reported confidence.'],
                  'finished_at':time.time()}
        self.emit(run,'run.completed',{'status':status,'metrics':report['metrics']})
        self.store.update_run(run,status,report)
        return report
