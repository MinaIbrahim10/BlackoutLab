import argparse
import json
import os
from pathlib import Path
import tempfile
import uvicorn
from .agents import OllamaAgents
from .db import Store
from .lab import Lab, SCENARIOS
from .transport import LocalTransport


def main():
    parser = argparse.ArgumentParser(description='Blackout Lab incident-response laboratory')
    sub = parser.add_subparsers(dest='command',required=True)
    serve = sub.add_parser('serve')
    serve.add_argument('--host',default='127.0.0.1')
    serve.add_argument('--port',default=8080,type=int)
    bench = sub.add_parser('benchmark')
    bench.add_argument('--mode',choices=['runbook','single','multi'],default='runbook')
    bench.add_argument('--trials',type=int,default=1)
    bench.add_argument('--output',type=Path,default=Path('benchmark.json'))
    args = parser.parse_args()
    if args.command == 'serve':
        uvicorn.run('blackout.api:create_app',factory=True,host=args.host,port=args.port,workers=1)
        return
    if not 1 <= args.trials <= 20: parser.error('trials must be between 1 and 20')
    reports = []
    with tempfile.TemporaryDirectory(prefix='blackout-benchmark-') as folder:
        root=Path(folder)
        store=Store(root/'control.sqlite')
        transport=LocalTransport(root)
        lab=Lab(store,transport,OllamaAgents() if args.mode!='runbook' else None)
        try:
            for scenario in SCENARIOS:
                for trial in range(args.trials):
                    run=store.create_run(scenario,args.mode)
                    report=lab.run(run,scenario,args.mode)
                    reports.append({'scenario':scenario,'trial':trial+1,'status':report['status'],**report['metrics']})
        finally: transport.close()
    summary={'mode':args.mode,'model':os.getenv('BLACKOUT_MODEL','gemma4:e4b') if args.mode!='runbook' else None,
             'trials_per_scenario':args.trials,'results':reports,
             'recovery_rate':sum(r['status']=='recovered' for r in reports)/len(reports),
             'note':'Runbook is a deterministic reference, not an AI performance measurement. Compare single/multi using the same model and trials.'}
    args.output.write_text(json.dumps(summary,indent=2)+'\n',encoding='utf-8')
    print(json.dumps(summary,indent=2))


if __name__ == '__main__': main()
