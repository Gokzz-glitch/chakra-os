import sys
from playwright.sync_api import sync_playwright
with sync_playwright() as w:
 b=w.chromium.launch(channel='chrome')
 p=b.new_page(viewport={'width':1440,'height':900})
 p.goto(sys.argv[1]+'/v2/admin',wait_until='domcontentloaded')
 p.get_by_role('button',name='7. Review & FL Curation').click()
 p.locator('#reviewRunSel').select_option('015b2ce7',timeout=45000)
 assert 'No recording or evidence frame was saved' in p.locator('#reviewNoMedia').inner_text()
 assert p.locator('#reviewVideo').is_hidden() and p.locator('#reviewVideo').get_attribute('src') is None
 p.get_by_role('button',name='Browse saved evaluation replays').click()
 p.locator('#eg-patient option[value="SIM-037"]').wait_for(state='attached',timeout=60000)
 p.select_option('#eg-patient','SIM-037')
 p.get_by_role('button',name='SIM-037 YOLOViT',exact=True).click(force=True)
 assert 'SIM-037' in p.locator('#eg-detail a',has_text='Replay').get_attribute('href')
 print('Verified missing recording and navigation to SIM-037 replay')
 b.close()
