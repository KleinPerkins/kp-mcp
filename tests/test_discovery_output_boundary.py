"""Private discovery output must not be reintroduced into publication source."""
from pathlib import Path
import subprocess
import sys
ROOT=Path(__file__).resolve().parents[1]
SCRIPT=ROOT/'tools/caller_matrix/scan.py'
def test_discovery_requires_explicit_root_and_output():
    result=subprocess.run([sys.executable,str(SCRIPT)],capture_output=True,text=True)
    assert result.returncode==2 and '--root' in result.stderr and '--out' in result.stderr

def test_discovery_cannot_write_inside_source(tmp_path):
    output=ROOT/'docs/discovery/forbidden-fixture.json'
    result=subprocess.run([sys.executable,str(SCRIPT),'--root',str(tmp_path),'--out',str(output)],capture_output=True,text=True)
    assert result.returncode==2 and 'outside the source checkout' in result.stderr
    assert not output.exists()

def test_discovery_accepts_explicit_private_destination(tmp_path):
    source=tmp_path/'input';source.mkdir()
    (source/'fixture.py').write_text('from scripts.google_auth import authenticate\n')
    output=tmp_path/'private-output'/'matrix.json'
    result=subprocess.run([sys.executable,str(SCRIPT),'--root',str(source),'--out',str(output)],capture_output=True,text=True)
    assert result.returncode==0,result.stderr
    assert output.is_file() and (output.parent/'CALLER-MATRIX.md').is_file()
