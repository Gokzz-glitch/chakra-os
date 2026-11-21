"""Browser smoke test against staged or production cloud results."""
import sys
from playwright.sync_api import sync_playwright
with sync_playwright() as pw:
    browser=pw.chromium.launch(channel="chrome",headless=True)
    page=browser.new_page(viewport={"width":1440,"height":900})
    page.goto(sys.argv[1],wait_until="domcontentloaded")
    page.locator("#eg-graph [aria-label='SIM-001']").wait_for(timeout=90000)
    assert page.locator("#eg-graph [role=button]").count()==300
    first=page.text_content("#eg-time")
    page.select_option("#eg-layout","galaxy")
    page.select_option("#eg-patient","SIM-001")
    page.get_by_role("button",name="SIM-001 SEPNet",exact=True).click(force=True)
    assert "SEPNet" in page.text_content("#eg-detail")
    assert page.locator("#eg-detail a",has_text="Masks").get_attribute("href").startswith("https://storage.cloud.google.com/")
    page.wait_for_function("(stamp)=>document.getElementById('eg-time').textContent!==stamp",arg=first,timeout=20000)
    print(page.text_content("#eg-count"),first,"->",page.text_content("#eg-time"),"300 nodes; private mask link verified")
    page.select_option("#eg-filter","dataset-labeled polyp")
    assert page.locator("#eg-graph [role=button]").count()==125
    browser.close()
