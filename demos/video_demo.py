from pathlib import Path
import json, uuid
from alfiq_b import core as c
from alfiq_b.agent import make_agent, TURN_SCHEMA

class VideoDemo:
    def __init__(self, work, *, mode='live'):
        if mode not in {'live','offline_fixture'}:
            raise ValueError('Unknown mode')
        self.mode=mode
        self.session_id='video-'+uuid.uuid4().hex[:8]
        self.root=Path(work)/'runs'/self.session_id
        self.agent=make_agent(self.root,mode=mode,provider='ollama',
                             llm_options={'num_ctx':4096,'timeout':120})
        self.outputs=[]
        print('Demo:',self.session_id,'/ mode:',mode,'/ fixtures:',mode!='live')
        print('Kayit:',self.root.resolve())

    def say(self,message,*,fixture_patch=None):
        if self.mode=='offline_fixture' and fixture_patch is not None:
            self.agent.model.set_fixture(fixture_patch)
        body=self.agent.run_turn(self.session_id,message)
        c.Draft202012Validator(TURN_SCHEMA).validate(body)
        self.outputs.append(body)
        c.atomic_json_write(self.root/f'turn-{len(self.outputs):02}.json',body)
        cart=body['cart'] or {}
        brief={'mode':self.mode,'fixtures':self.mode!='live','user':message,
               'status':body['status'],'reason':body['reason_code'],
               'cart_state':cart.get('state'),'ids':cart.get('selected_ids'),
               'total':(cart.get('quote_snapshot') or {}).get('net_total'),
               'approval':body['approval'],'diff':body['diff'],
               'order':body['simulated_order'],
               'llm_calls':len(body['trace']['llm_calls'])}
        print(json.dumps(brief,ensure_ascii=False,indent=2))
        return body

    def patch(self):
        before=self.agent.tools.manager.bundle['quality_report']
        c.atomic_json_write(self.root/'quality-before-patch.json',before)
        result=self.agent.tools.manager.apply_patch(c.PACKAGE_DIR.parent/'examples'/'drift_patch.json')
        c.atomic_json_write(self.root/'patch-result.json',result)
        c.atomic_json_write(self.root/'quality-after-patch.json',self.agent.tools.manager.bundle['quality_report'])
        print(json.dumps(result,ensure_ascii=False,indent=2,default=c.json_default))
        if not result['ok']:
            raise RuntimeError('Demo patch failed')
        return result
