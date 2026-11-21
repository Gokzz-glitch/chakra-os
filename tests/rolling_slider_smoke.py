import math,sys
from playwright.sync_api import sync_playwright
with sync_playwright() as pw:
    browser=pw.chromium.launch(channel="chrome")
    for mobile in (False,True):
        page=browser.new_page(viewport={"width":390 if mobile else 1440,"height":844},has_touch=mobile)
        page.goto(sys.argv[1],wait_until="domcontentloaded")
        if mobile: page.locator(".mobile-sections").select_option("0")
        else: page.get_by_role("button",name="1. Setup & Pairing").click()
        wheel=page.locator(".conf-wheel.ready")
        wheel.wait_for()
        slider=page.get_by_role("slider",name="Confidence Threshold",exact=False)
        slider.focus()
        box=slider.bounding_box()
        def values():
            return wheel.evaluate("""w=>['--travel','--angle','--wheel'].map(k=>parseFloat(getComputedStyle(w).getPropertyValue(k)))""")
        slider.press("Home")
        assert values()[0]==0
        slider.press("ArrowRight")
        x,a,d=values()
        assert x>0 and math.isclose(a,x*360/(math.pi*d)) and page.locator("#confVal").inner_text()=="0.20"
        slider.press("End")
        high=values()[0]
        assert abs(high-(box["width"]-d))<1
        if mobile: page.touchscreen.tap(box["x"]+box["width"]*.4,box["y"]+22)
        else:
            page.mouse.move(box["x"]+box["width"]-d/2,box["y"]+22)
            page.mouse.down();page.mouse.move(box["x"]+box["width"]*.4,box["y"]+22,steps=8);page.mouse.up()
        assert 0<values()[0]<high
        print("Touch" if mobile else "Mouse","and keyboard passed; threshold",slider.input_value())
        page.close()
    browser.close()
