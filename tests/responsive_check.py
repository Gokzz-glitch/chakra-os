import sys
from pathlib import Path
from playwright.sync_api import sync_playwright
base=sys.argv[1]
routes={'admin':'/v2/admin','doctor':'/v2/doctor','phone':'/v2/phone','legacy':'/v1','map':'/v2/doctor/history'}
files={'admin':'admin.html','doctor':'doctor.html','phone':'phone.html','legacy':'index_v1.html','map':'static/patient-history.html'}
errors=[]
with sync_playwright() as pw:
 b=pw.chromium.launch(channel='chrome')
 for width,height in [(320,640),(390,844),(768,1024),(1024,768),(1536,864)]:
  p=b.new_page(viewport={'width':width,'height':height})
  for key,route in routes.items():
   p.goto(base+route if base.startswith('http') else (Path(base)/files[key]).as_uri(),wait_until='domcontentloaded')
   def check(label):
    over=p.evaluate('document.documentElement.scrollWidth-innerWidth')
    if over>1:
     bad=p.evaluate("Array.from(document.querySelectorAll('body *')).filter(e=>e.getBoundingClientRect().right>innerWidth+1 && !e.closest('.eg-scroll') && !e.closest('#historyGraph')).slice(0,6).map(e=>e.tagName+'.'+e.className)")
     errors.append((width,key,label,over,bad))
   check('initial')
   if key=='admin':
    nav=p.locator('.side .nav')
    for i in range(nav.count()):
     if width<=800:p.locator('.mobile-sections').select_option(str(i))
     else:nav.nth(i).click()
     check(str(i))
   if key=='doctor':
    p.locator('#openHistory').click()
    check('history')
  p.close()
 b.close()
print('Viewport checks',errors or 'passed');sys.exit(bool(errors))
