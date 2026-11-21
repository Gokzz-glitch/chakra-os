import sys
from playwright.sync_api import sync_playwright
base=sys.argv[1]
with sync_playwright() as pw:
 b=pw.chromium.launch(channel='chrome')
 p=b.new_page(viewport={'width':1440,'height':900})
 p.add_init_script("""window.pulses=[]; Object.defineProperty(navigator,'vibrate',{value:v=>{window.pulses.push(v);return true}})""")
 p.goto(base+'/v2/admin',wait_until='domcontentloaded')
 prefs=p.locator('#chakra-feedback-settings')
 prefs.locator('summary').click()
 prefs.get_by_label('Sound',exact=True).check()
 prefs.get_by_label('Vibration',exact=True).check()
 assert p.evaluate('pulses.length')>0
 prefs.locator('summary').click()
 p.get_by_role('button',name='1. Setup & Pairing').click()
 slider=p.locator('#confRange');slider.focus();slider.press('ArrowRight')
 assert 'threshold 0.50' in p.locator('#chakra-feedback-status').inner_text()
 p.route('**/api/v2/rooms/*/config',lambda route:route.fulfill(status=503,body='test unavailable'))
 p.get_by_role('button',name='Apply Live Configuration').click()
 p.wait_for_function("document.querySelector('#chakra-feedback-status').dataset.kind==='error'")
 p.unroute('**/api/v2/rooms/*/config')
 p.get_by_role('button',name='Apply Live Configuration').click()
 p.wait_for_function("document.querySelector('#chakra-feedback-status').textContent==='Done · Apply configuration'")
 for route in ['/v2/doctor','/v2/phone','/v2/doctor/history','/v1']:
  p.goto(base+route,wait_until='domcontentloaded');prefs.locator('summary').click()
  assert prefs.get_by_label('Sound',exact=True).is_checked()
 print('Verified feedback preferences across five pages, slider input, successful configuration, simulated failure, and vibration API calls.')
 b.close()
