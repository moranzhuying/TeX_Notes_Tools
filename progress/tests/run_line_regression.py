"""可复跑全套定位改动回归及真实源码SHA256保护。"""
import hashlib
import json
import os
from pathlib import Path
import subprocess
import sys

WS = Path(__file__).resolve().parents[3]
OUT = WS / 'outputs/workbench_line_verify_20261013'
OUT.mkdir(parents=True, exist_ok=True)
TESTS = Path(__file__).parent

def hashes():
    return {str(p.relative_to(WS)): hashlib.sha256(p.read_bytes()).hexdigest()
            for p in (WS / 'LaTeX_Notes').rglob('*') if p.is_file()}

before = hashes()
(OUT / 'source_before.json').write_text(json.dumps(before,ensure_ascii=False),encoding='utf-8')
env = dict(os.environ)
result = {'commands': []}
try:
    for name in ('test_line_snapshot.py','test_daily.py','test_daily_independent.py','test_workbench_launcher.py','test_gt_daily.py','browser_line_snapshot.py','browser_daily.py'):
        p = subprocess.run([sys.executable,'-X','utf8',str(TESTS / name)],capture_output=True,env=env)
        result['commands'].append({'test':name,'exit':p.returncode,'stdout':p.stdout.decode('utf-8',errors='replace'),'stderr':p.stderr.decode('utf-8',errors='replace')})
        print(name,p.returncode,flush=True)
finally:
    after = hashes()
    result['source_hash_count'] = len(before)
    result['source_changed'] = [k for k in before.keys() | after.keys() if before.get(k) != after.get(k)]
    (OUT / 'regression.json').write_text(json.dumps(result,ensure_ascii=False,indent=2),encoding='utf-8',newline='\n')
assert not result['source_changed'], result['source_changed']
assert all(x['exit']==0 for x in result['commands'])
