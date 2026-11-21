import json,concurrent.futures
from pathlib import Path
from google.auth import default
from google.auth.transport.requests import AuthorizedSession
def status(item):
    region,raw=item
    name=json.loads(raw)['metadata']['name']
    location=region.removesuffix('-cpu')
    url=f'https://run.googleapis.com/v2/projects/girpolypposframesrealcolon/locations/{location}/jobs/'+('chakra-mixed-fast-cpu' if region.endswith('-cpu') else 'chakra-mixed-fast')+'/executions/'+name
    session=AuthorizedSession(default(scopes=['https://www.googleapis.com/auth/cloud-platform'])[0])
    resp=session.get(url,timeout=30);resp.raise_for_status();r=resp.json()
    return {'region':region,'execution':name,'running':r.get('runningCount',0),'done':r.get('succeededCount',0),'failed':r.get('failedCount',0),'retries':r.get('retriedCount',0),'finished':r.get('completionTime')}
if __name__=='__main__':
    with concurrent.futures.ThreadPoolExecutor(max_workers=6) as pool: rows=list(pool.map(status,json.loads(Path('shard-dispatch.json').read_text()).items()))
    print(json.dumps(rows))
    print({k:sum(r[k] for r in rows) for k in ('running','done','failed','retries')})
