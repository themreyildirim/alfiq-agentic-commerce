"""Apply a provided product-list patch to one persisted session root; no inference."""
from pathlib import Path
import argparse, sys
sys.path.insert(0,str(Path(__file__).resolve().parents[1]))
from alfiq_b import core as c
from alfiq_b.agent import make_agent
p=argparse.ArgumentParser()
p.add_argument('--state-root',required=True)
p.add_argument('--patch',required=True)
a=p.parse_args()
root=Path(a.state_root)
agent=make_agent(root)
c.atomic_json_write(root/'quality-before-patch.json',agent.tools.manager.bundle['quality_report'])
result=agent.tools.manager.apply_patch(Path(a.patch))
c.atomic_json_write(root/'patch-result.json',result)
c.atomic_json_write(root/'quality-after-patch.json',agent.tools.manager.bundle['quality_report'])
print(c.canonical_json(result))
raise SystemExit(0 if result['ok'] else 2)
