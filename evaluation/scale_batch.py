"""Deploy disjoint Cloud Run task shards and hand off a running evaluation."""
import concurrent.futures, json, os, subprocess, time
from pathlib import Path
from google.cloud import storage

PROJECT='girpolypposframesrealcolon'
HOME_REGION='asia-southeast1'
REGIONS=['asia-east1','asia-northeast1','asia-south1','asia-southeast2','asia-southeast1-cpu']
BATCH='chakra-mixed-evaluation-kkq65'
BUCKET='girpolypposframesrealcolon-chakra-models'
BUILD='0672567d-cb2d-410b-b4cc-5fc8f52e7681'
GCLOUD=Path(os.environ['LOCALAPPDATA'])/'CHAKRA/BuildathonTools/google-cloud-sdk/bin/gcloud.cmd'
MODELS=['yolovit_vit','chakranet','pvt_pranet','sepnet']
def cli(*args):
    res=subprocess.run([str(GCLOUD),*args,'--project='+PROJECT,'--quiet'],capture_output=True,text=True,errors='replace')
    if res.returncode: raise RuntimeError(res.stderr[-1800:])
    return res.stdout.strip()
def parallel(fn, items):
    with concurrent.futures.ThreadPoolExecutor(max_workers=8) as pool:
        return list(pool.map(fn,items))
def main():
    while True:
        build=json.loads(cli('builds','describe',BUILD,'--region='+HOME_REGION,'--format=json'))
        if build['status']=='SUCCESS':break
        if build['status'] not in ('QUEUED','WORKING','PENDING'):raise RuntimeError(build['status'])
        time.sleep(15)
    image=build['results']['images'][0]
    pinned=image['name'].rsplit(':',1)[0]+'@'+image['digest']
    bucket=storage.Client(project=PROJECT).bucket(BUCKET)
    rows=json.loads(bucket.blob('evaluation-runs/cohorts/mixed-v1.json').download_as_bytes())
    completed={b.name for b in bucket.list_blobs(prefix='evaluation-runs/SIM-') if b.name.endswith('/'+BATCH+'/complete.json')}
    pending=[i for i in range(240) if f"evaluation-runs/{rows[i//4]['patient_id']}/{MODELS[i%4]}/{BATCH}/complete.json" not in completed]
    # The longest segmentation videos benefit most from scarce GPU slots.
    priority=sorted(pending,key=lambda i:rows[i//4]['frames']*(1 if i%4 else .25),reverse=True)
    gpu=priority[:6]; cpu=priority[6:]
    shards={region:cpu[i::len(REGIONS)] for i,region in enumerate(REGIONS)}
    shards[HOME_REGION]=gpu
    assert sorted(i for block in shards.values() for i in block)==sorted(pending)
    def deploy(region):
        indices=shards[region]; gpu_job=region==HOME_REGION
        name='chakra-mixed-fast-cpu' if region.endswith('-cpu') else 'chakra-mixed-fast'
        location=region.removesuffix('-cpu')
        key=f'evaluation-runs/cohorts/{BATCH}-shards/{region}.json'
        bucket.blob(key).upload_from_string(json.dumps(indices),content_type='application/json')
        flags=['--gpu=1','--gpu-type=nvidia-l4','--no-gpu-zonal-redundancy'] if gpu_job else []
        cli('run','jobs','deploy',name,'--region='+location,'--image='+pinned,'--tasks='+str(len(indices)),
            '--parallelism='+str(3 if gpu_job else min(45,len(indices))),'--cpu=4','--memory='+('16Gi' if gpu_job else '8Gi'),
            '--max-retries=1','--task-timeout='+('3600' if gpu_job else '14400'),
            '--set-env-vars=TASK_MAP='+key+',EVAL_BATCH='+BATCH+',EVAL_DEVICE='+('cuda' if gpu_job else 'cpu'),*flags)
        print('Provisioned',region,len(indices),flush=True)
    parallel(deploy,list(shards))
    # Preserve existing completed artifacts. All unfinished old tasks are re-assigned.
    state=json.loads(cli('run','jobs','executions','describe',BATCH,'--region='+HOME_REGION,'--format=json'))['status']
    if not state.get('completionTime'):
        cli('run','jobs','executions','cancel',BATCH,'--region='+HOME_REGION)
        for _ in range(120):
            state=json.loads(cli('run','jobs','executions','describe',BATCH,'--region='+HOME_REGION,'--format=json'))['status']
            if state.get('completionTime') or not state.get('runningCount',0): break
            time.sleep(2)
        else: raise RuntimeError('Original tasks are still running')
    def launch(region):
        name='chakra-mixed-fast-cpu' if region.endswith('-cpu') else 'chakra-mixed-fast'
        result=cli('run','jobs','execute',name,'--region='+region.removesuffix('-cpu'),'--async','--format=json')
        print('Dispatched',region,result[:140],flush=True)
        return region,result
    executions=parallel(launch,list(shards))
    Path('shard-dispatch.json').write_text(json.dumps(dict(executions),indent=2))
if __name__=='__main__':
    main()
