"""Browser regression check. Run with pytest tests/browser_clinical_smoke.py and Playwright Chrome."""

import pytest
from fastapi.testclient import TestClient
from playwright.sync_api import sync_playwright
from urllib.parse import urlsplit
import main


@pytest.mark.parametrize(
    "path,role",
    [
        ("/v2/admin", "operator"),
        ("/v2/admin", "clinician"),
        ("/v2/doctor", "clinician"),
        ("/v2/phone", "operator"),
        ("/v1", "clinician"),
        ("/v2/doctor/history", "clinician"),
    ],
)
def test_real_browser_under_csp(path, role):
    errors = []
    sample = "<b>Synthetic finding</b>"
    main.PATIENT_REGISTRY["DEMO-PATIENT-01"]["encounters"][0][
        "clinical_narrative"
    ] = sample
    with sync_playwright() as driver, TestClient(main.app) as api:
        browser = driver.chromium.launch(channel="chrome")
        page = browser.new_page()
        page.on("pageerror", lambda error: errors.append(str(error)))
        page.add_init_script(
            """window.violations = [];
            addEventListener('securitypolicyviolation', e => violations.push(e.effectiveDirective));"""
        )

        def serve(route):
            req = route.request
            parsed = urlsplit(req.url)
            assert parsed.netloc == "testserver"
            target = parsed.path + ("?" + parsed.query if parsed.query else "")
            headers = {
                k: v for k, v in req.headers.items() if k in ("origin", "content-type")
            }
            headers["x-goog-iap-jwt-assertion"] = role
            response = api.request(
                req.method, target, content=req.post_data_buffer, headers=headers
            )
            route.fulfill(
                status=response.status_code,
                headers=dict(response.headers),
                body=response.content,
            )

        page.route("**/*", serve)
        page.route_web_socket("**/ws/**", lambda ws: None)
        page.goto("http://testserver" + path)
        if path == "/v2/admin":
            page.wait_for_function(
                "document.querySelector('#deploymentRegion').textContent === 'test'"
            )
            if role == "operator":
                page.get_by_role("button", name="1. Setup & Pairing").click()
                page.wait_for_selector("#qrInline canvas", state="attached")
                assert not page.get_by_role(
                    "button", name="5. Patient History & Reconciliation"
                ).is_visible()
            else:
                page.get_by_role(
                    "button", name="5. Patient History & Reconciliation"
                ).click()
                page.locator("#encountersList").get_by_text(
                    sample, exact=True
                ).wait_for()
                assert not page.locator("#encountersList b").count()
        if path == "/v2/doctor":
            assert page.locator("#measurements input:invalid").count() == 4
            page.evaluate(
                "renderFindings([{id:'<b>Synthetic finding</b>',conf:0.8,status:'pending'}])"
            )
            assert sample in page.locator("#findingsList").text_content()
            assert not page.locator("#findingsList b").count()
        if path == "/v2/doctor/history":
            page.wait_for_selector("#historyGraph svg")
        assert not page.evaluate("window.violations")
        assert not errors, errors
        browser.close()
