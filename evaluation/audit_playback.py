import concurrent.futures,json,tempfile
from pathlib import Path
from google.cloud import storage
from replay_validation import validate_replay
bucket=storage.Client(project='girpolypposframesrealcolon').bucket('girpolypposframesrealcolon-chakra-models')
cohort=json.loads(bucket.blob('evaluation-runs/cohorts/mixed-v1.json').download_as_bytes())
batch='chakra-mixed-evaluation-kkq65'
models=['yolovit_vit','chakranet','pvt_pranet','sepnet']
def check(item):
    row,model=item
    prefix=f"evaluation-runs/{row['patient_id']}/{model}/{batch}/"
    receipt=json.loads(bucket.blob(prefix+'complete.json').download_as_bytes())
    generation=int(receipt['artifacts']['replay.mp4'])
    with tempfile.TemporaryDirectory() as d:
        p=Path(d)/'replay.mp4'
        bucket.blob(prefix+'replay.mp4',generation=generation).download_to_filename(str(p),checksum='auto')
        result=validate_replay(p,row['frames'])
    return dict(patient=row['patient_id'],model=model,generation=str(generation),**result)
if __name__=='__main__':
    rows=[];errors=[]
    with concurrent.futures.ThreadPoolExecutor(max_workers=10) as pool:
        jobs={pool.submit(check,(r,m)):(r['patient_id'],m) for r in cohort for m in models}
        for job in concurrent.futures.as_completed(jobs):
            try: rows.append(job.result())
            except Exception as exc: errors.append([*jobs[job],str(exc)])
            if (len(rows)+len(errors))%20==0: print('Passed',len(rows),'errors',len(errors),flush=True)
    report={'batch':batch,'passed':len(rows),'decoded_frames':sum(r['decoded_frames'] for r in rows),'errors':errors,'replays':rows}
    path=Path(__file__).parent/'playback-audit.json';path.write_text(json.dumps(report,indent=2))
    print('Result',report['passed'],report['decoded_frames'],errors[:4],flush=True)
    if len(rows)!=240 or errors: raise SystemExit(1)
    bucket.blob('evaluation-runs/cohorts/'+batch+'-playback-audit.json').upload_from_filename(str(path))
