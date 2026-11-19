"""Validate capability parity and byte-stable generated public references."""
from pathlib import Path
import subprocess
import sys
ROOT=Path(__file__).resolve().parents[1]
def snapshot():
    return {str(p.relative_to(ROOT)):p.read_bytes() for base in [ROOT/'docs',*[ROOT/(kit+'/docs') for kit in ('google-kit','snow-kit','widget-kit')]] for p in base.rglob('*') if p.is_file()}
subprocess.run(['bash','.github/scripts/verify-capabilities.sh'],cwd=ROOT,check=True)
before=snapshot()
for _ in range(2):
    for kit in ('google-kit','snow-kit','widget-kit'):
        subprocess.run([sys.executable,'tools/ci_discover.py','regen','--kit',kit],cwd=ROOT,check=True)
    subprocess.run([sys.executable,'tools/ci_discover.py','regen-catalog'],cwd=ROOT,check=True)
    after=snapshot()
    changed=sorted(k for k in before.keys()|after.keys() if before.get(k)!=after.get(k))
    if changed: raise SystemExit('Generated public references differ: '+', '.join(changed))
print('Capability metadata and generated reference determinism passed')
