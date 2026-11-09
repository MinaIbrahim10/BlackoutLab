import pathlib,json,tempfile,urllib.request,time
from blackout.lab import Lab
from blackout.db import Store
from blackout.transport import LocalTransport
from blackout.agents import OllamaAgents
from blackout.lab import SCENARIOS
root=pathlib.Path('/content/lab-closed-loop/closed-loop-evidence')
req=urllib.request.Request('http://127.0.0.1:11434/api/chat',data=json.dumps({'model':'gemma4:e4b','stream':False,'think':False,'messages':[{'role':'user','content':'Reply OK'}],'options':{'num_ctx':8192,'num_predict':20}}).encode(),headers={'Content-Type':'application/json'})
print('WARMING',flush=True)
with urllib.request.urlopen(req,timeout=600) as response: print('WARMED',json.load(response)['done_reason'],flush=True)
summary=[]
for mode in ['runbook','single','multi']:
 for trial in range(1 if mode=='runbook' else 3):
  for scenario in SCENARIOS:
   with tempfile.TemporaryDirectory() as folder:
    path=pathlib.Path(folder); transport=LocalTransport(path)
    try:
     store=Store(path/'control.sqlite'); lab=Lab(store,transport,None if mode=='runbook' else OllamaAgents(),max_rounds=3)
     rid=store.create_run(scenario,mode); report=lab.run(rid,scenario,mode)
     (root/f'{mode}-{scenario}-{trial+1}.json').write_text(json.dumps(report,indent=2))
     row={'mode':mode,'scenario':scenario,'trial':trial+1,'status':report['status'],**report['metrics']}; summary.append(row)
     (root/'summary.json').write_text(json.dumps(summary,indent=2)); print(json.dumps(row),flush=True)
    finally: transport.close()
print('CLOSED_LOOP_EXPERIMENT_COMPLETE',flush=True)
