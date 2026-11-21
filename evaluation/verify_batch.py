"""Verify each published run against its patient, checkpoint and uploaded objects."""
import concurrent.futures, json
from collections import Counter
from pathlib import Path
from google.cloud import storage

BATCH='chakra-mixed-evaluation-kkq65'
EXPECTED={
 'yolovit_vit':'60773197d6be9634bf5008860c6346f622f6072efb5570c25ff128dfcfa685a0',
 'chakranet':'de81ed331e86782da2a0db3572d2f36c24ce4248effc0d0956cd4578931fd044',
 'pvt_pranet':'7333230d864eec66763852843177adc3ec45a5ed651f616f18ce93ecf7ca90b3',
 'sepnet':'dcc38afda2430bfe4aaa361655579386c5ae5c2acd0a9e9aec13b7f8a9c284b3'}
bucket=storage.Client(project='girpolypposframesrealcolon').bucket('girpolypposframesrealcolon-chakra-models')
rows={r['patient_id']:r for r in json.loads(bucket.blob('evaluation-runs/cohorts/mixed-v1.json').download_as_bytes())}
objects={b.name:b for b in bucket.list_blobs(prefix='evaluation-runs/SIM-')}
def verify(name):
    r=json.loads(objects[name].download_as_bytes()); patient=r['patient_id']; model=r['model']; row=rows[patient]
    assert name==f'evaluation-runs/{patient}/{model}/{BATCH}/complete.json'
    assert r['checkpoint_sha256']==EXPECTED[model] and r['source_sha256']==row['sha256']
    assert r['frames']==row['frames'] and r['skipped']==0 and r['threshold']==.7 and r['run_id']==BATCH
    keys={'frames.jsonl','replay.mp4'}
    if model!='yolovit_vit':keys.add('masks.zip')
    assert keys==set(r['artifacts'])
    for key,gen in r['artifacts'].items():
        obj=objects[name.rsplit('/',1)[0]+'/'+key]
        assert str(obj.generation)==gen and obj.size>0
    return r
names=[name for name in objects if name.endswith('/'+BATCH+'/complete.json')]
with concurrent.futures.ThreadPoolExecutor(max_workers=12) as pool:
    results=list(pool.map(verify,names))
summary=dict(verified_runs=len(results),expected_runs=240,verified_frames=sum(r['frames'] for r in results),
    by_model=dict(Counter(r['model'] for r in results)),by_device=dict(Counter(r.get('compute_device','cuda') for r in results)))
print(json.dumps(summary))
if len(results)==240:
    report=dict(summary=summary,runs=results)
    dest=Path(__file__).parent/'verified-results.json'
    dest.write_text(json.dumps(report,indent=2))
    bucket.blob(f'evaluation-runs/cohorts/{BATCH}-verified.json').upload_from_filename(str(dest))
