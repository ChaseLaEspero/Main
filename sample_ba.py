from pathlib import Path
import json
import requests
import urllib3
import sample_fast

urllib3.disable_warnings(urllib3.exceptions.InsecureRequestWarning)

_OrigSession = requests.Session
class InsecureSession(_OrigSession):
    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        self.verify = False

sample_fast.requests.Session = InsecureSession
sample_fast.ROOT = Path('ba_samples')
sample_fast.ROOT.mkdir(exist_ok=True)

cfg = {
    'base': 'https://www.doe.ba.gov.br',
    'toc': '/html/{id}.html',
}
summary = sample_fast.run('BA', cfg)
print(json.dumps(summary, ensure_ascii=False, indent=2), flush=True)
if summary['sample_count'] < 100:
    raise SystemExit(f"Only {summary['sample_count']} BA samples were produced")
