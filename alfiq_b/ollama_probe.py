"""One explicitly enabled real local inference, not a benchmark or canned answer."""
import argparse
import time
from jsonschema import ValidationError
from . import core as c
from .models import build_live_adapter

def run_probe(*,allow_live=False,num_ctx=4096,timeout=120,output=None):
    if not allow_live:
        raise ValueError('Set allow_live=True to send one request to local Ollama')
    adapter = build_live_adapter('ollama',options={'num_ctx':num_ctx,'timeout':timeout})
    schema = {'type':'object','properties':{'status':{'type':'string','enum':['ready']}},
              'required':['status'],'additionalProperties':False}
    started = time.perf_counter()
    try:
        answer = adapter.generate_json(schema,{'task':'Return status ready.'},
                    'Return only JSON with status ready.',stage='connection_test')
        c.Draft202012Validator(schema).validate(answer)
        report = {'ok':True,'provider':'ollama','mode':'live','uses_llm_fixtures':False,
                  'answer':answer,'llm_calls':adapter.traces,'api_attempts':adapter.client.attempts,
                  'configuration':adapter.client.configuration,'latency_ms':round((time.perf_counter()-started)*1000,1)}
    except (c.LLMServiceError,ValidationError) as exc:
        report = {'ok':False,'provider':'ollama','mode':'live','uses_llm_fixtures':False,
                  'error':str(exc),'detail':adapter.last_error,'llm_calls':adapter.traces,
                  'api_attempts':adapter.client.attempts,'latency_ms':round((time.perf_counter()-started)*1000,1)}
    if output is not None:c.atomic_json_write(c.Path(output),report)
    return report

def main():
    parser = argparse.ArgumentParser()
    parser.add_argument('--allow-live',action='store_true')
    parser.add_argument('--num-ctx',type=int,default=4096)
    parser.add_argument('--timeout',type=float,default=120)
    parser.add_argument('--output')
    args = parser.parse_args()
    report = run_probe(allow_live=args.allow_live,num_ctx=args.num_ctx,timeout=args.timeout,output=args.output)
    print(c.json.dumps(report,ensure_ascii=True,indent=2))
    return 0 if report['ok'] else 1

if __name__ == '__main__':raise SystemExit(main())
