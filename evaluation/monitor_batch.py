import concurrent.futures,json,subprocess,sys,time
from pathlib import Path
from shard_status import status
items=list(json.loads(Path('shard-dispatch.json').read_text()).items())
last=None
while True:
    try:
        with concurrent.futures.ThreadPoolExecutor(max_workers=6) as pool:
            rows=list(pool.map(status,items))
        totals={k:sum(r[k] for r in rows) for k in ('running','done','failed','retries')}
        if totals!=last:
            print(time.strftime('%H:%M:%S'),totals,flush=True);last=totals
        if all(r['finished'] for r in rows):
            subprocess.run([sys.executable,'verify_batch.py'],check=True)
            break
    except Exception as exc: print(type(exc).__name__,str(exc)[:150],flush=True)
    time.sleep(30)
