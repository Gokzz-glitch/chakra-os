import sys
from playwright.sync_api import sync_playwright
with sync_playwright() as pw:
 b=pw.chromium.launch(channel="chrome")
 p=b.new_page(viewport={"width":1440,"height":900})
 p.goto(sys.argv[1]+"/v2/admin",wait_until="domcontentloaded")
 p.get_by_role("button",name="7. Review & FL Curation").click()
 for run,disabled in [("2abe559e",2),("d80e0cd7",0)]:
  p.locator("#reviewRunSel").select_option(run,timeout=45000)
  v=p.locator("#reviewVideo")
  p.wait_for_function("document.querySelector('#reviewVideo').readyState>=2",timeout=30000)
  metrics=v.evaluate("""async v=>{v.muted=true;await v.play();await new Promise(done=>v.requestVideoFrameCallback(done));const c=document.createElement('canvas');c.width=64;c.height=48;const ctx=c.getContext('2d');ctx.drawImage(v,0,0,64,48);const d=ctx.getImageData(0,0,64,48).data;let lit=0;for(let i=0;i<d.length;i+=4)if(d[i]>30)lit++;return [v.videoWidth,v.videoHeight,v.duration,lit]}""")
  assert metrics[:2]==[512,384] and abs(metrics[2]-1.6)<.05 and metrics[3]>300, metrics
  assert p.locator('#evidenceChips button:disabled').count()==disabled
  print("Verified decoded video",metrics)
 b.close()
