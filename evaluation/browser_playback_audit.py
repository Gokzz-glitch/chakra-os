"""Independently check Chrome can present the first frame of every private replay."""
from concurrent.futures import ThreadPoolExecutor
import json,tempfile
from pathlib import Path
from google.cloud import storage
from playwright.sync_api import sync_playwright
batch='chakra-mixed-evaluation-kkq65'
bucket=storage.Client(project='girpolypposframesrealcolon').bucket('girpolypposframesrealcolon-chakra-models')
blobs=[b for b in bucket.list_blobs(prefix='evaluation-runs/SIM-',match_glob='**/replay.mp4') if b.name.endswith('/'+batch+'/replay.mp4')]
def inspect(group):
    successes=[];failed=[]
    with sync_playwright() as pw,tempfile.TemporaryDirectory() as tmp:
        browser=pw.chromium.launch(channel='chrome');page=browser.new_page()
        for obj in group:
            try:
                path=Path(tmp)/(obj.name.split('/')[1]+'-'+obj.name.split('/')[2]+'.mp4')
                path.write_bytes(obj.download_as_bytes(start=0,end=min(1024*1024,obj.size)-1,if_generation_match=obj.generation))
                html=Path(tmp)/'probe.html';html.write_text(f'<video src="{path.name}" muted autoplay></video>')
                page.goto(html.as_uri(),wait_until='domcontentloaded')
                page.wait_for_function('document.querySelector("video").getVideoPlaybackQuality().totalVideoFrames>0 && document.querySelector("video").readyState>=2',timeout=12000)
                assert page.locator('video').evaluate('v=>v.videoWidth>0 && v.videoHeight>0')
                successes.append(obj.name);path.unlink()
            except Exception as err:failed.append([obj.name,str(err)])
        browser.close()
    return successes,failed
if __name__=='__main__':
    with ThreadPoolExecutor(max_workers=4) as pool: out=list(pool.map(inspect,[blobs[i::4] for i in range(4)]))
    ok=sum((a for a,_ in out),[]);bad=sum((b for _,b in out),[])
    print('Chrome first-frame checks',len(ok),'failed',len(bad),bad[:2],flush=True)
    Path('browser-playback-audit.json').write_text(json.dumps({'passed':ok,'errors':bad},indent=2))
    if len(ok)!=240 or bad:raise SystemExit(1)
