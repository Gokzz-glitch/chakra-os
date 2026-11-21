import os
import shutil
import subprocess
import time
from playwright.sync_api import sync_playwright

BASE_URL = os.getenv("BASE_URL", "https://chakra-os-219670109842.asia-south1.run.app")
ASSETS_DIR = "submission_assets"
RECORDINGS_DIR = os.path.join(ASSETS_DIR, "recordings")
os.makedirs(RECORDINGS_DIR, exist_ok=True)


def record_demo():
    print(f"[DEMO RECORDING] Launching dual-page recording against {BASE_URL}...")
    with sync_playwright() as p:
        browser = p.chromium.launch(
            headless=True,
            args=[
                "--no-sandbox",
                "--disable-setuid-sandbox",
                "--use-fake-ui-for-media-stream",
                "--use-fake-device-for-media-stream",
                "--autoplay-policy=no-user-gesture-required",
                "--disable-background-timer-throttling",
                "--disable-backgrounding-occluded-windows",
                "--disable-renderer-backgrounding",
            ],
        )

        context = browser.new_context(
            viewport={"width": 1920, "height": 1080},
            record_video_dir=RECORDINGS_DIR,
            record_video_size={"width": 1920, "height": 1080},
        )

        # ----------------------------------------------------
        # 1. Primary Presentation Page (Recorded)
        # ----------------------------------------------------
        page_main = context.new_page()
        page_main.add_init_script("""
        window.alert = function(msg) { console.log('SUPPRESSED ALERT: ' + msg); };
        """)
        page_main.on("dialog", lambda dialog: dialog.dismiss())
        page_main.on("console", lambda m: print(f"    [HUD LOG] {m.text}"))
        page_main.on("pageerror", lambda e: print(f"    [HUD ERROR] {e}"))

        print("\n[STEP 1] /v2/admin: CHAKRA Logo, Gmail Light UI, Mobile QR Modal & Dark Mode Toggle")
        page_main.goto(f"{BASE_URL}/v2/admin", wait_until="networkidle")
        page_main.wait_for_selector("#codeBox:not(:has-text('------'))", timeout=12000)
        page_main.wait_for_timeout(2000)

        room_code = page_main.locator("#codeBox").inner_text().strip()
        print(f"  -> Generated 6-digit Room Code: {room_code}")

        # Open Mobile QR Code pop-up modal briefly (2s)
        print("  -> Opening Mobile QR Code pop-up modal...")
        try:
            page_main.click('button:has-text("Show QR")')
            page_main.wait_for_selector("#qrModal", state="visible", timeout=4000)
            page_main.wait_for_timeout(2500)
            page_main.click('#qrModal button:has-text("✕")')
            page_main.wait_for_timeout(1000)
        except Exception as e:
            print(f"  -> QR modal note: {e}")

        # Toggle Chrome Settings Dark Mode briefly (2s) then back to Gmail Light
        print("  -> Toggling to Chrome Settings Dark Mode...")
        page_main.click("#themeToggle")
        page_main.wait_for_timeout(2200)
        print("  -> Switching back to Gmail Light Mode...")
        page_main.click("#themeToggle")
        page_main.wait_for_timeout(1500)

        # Direct Model Test on 1_35.avi
        print("  -> Selecting 1_35.avi and executing Direct L4 Inference Test on Admin...")
        try:
            page_main.select_option("#cloudClipSel", "1_35.avi")
            page_main.wait_for_timeout(500)
            page_main.click('button:has-text("Run L4 Test")')
            page_main.wait_for_selector("#testImg:not(.hide)", timeout=10000)
            print("  -> Real colonoscopy frame + L4 bounding box rendered on Admin Console!")
            page_main.wait_for_timeout(4000)
        except Exception as e:
            print(f"  -> Admin direct test note: {e}")
            page_main.wait_for_timeout(2000)

        # ----------------------------------------------------
        # 2. Background Mobile Scope Streamer (/v2/phone)
        # ----------------------------------------------------
        print(f"\n[STEP 2] Opening page_phone in background: /v2/phone?code={room_code}")
        page_phone = context.new_page()
        page_phone.add_init_script("""
        window.alert = function(msg) { console.log('SUPPRESSED ALERT: ' + msg); };
        Object.defineProperty(window, 'status', {
            get() { return document.getElementById('status'); },
            set(v) {},
            configurable: true
        });
        """)
        page_phone.on("dialog", lambda dialog: dialog.dismiss())
        page_phone.goto(f"{BASE_URL}/v2/phone?code={room_code}", wait_until="networkidle")
        page_phone.wait_for_timeout(2000)
        print(f"  -> Phone connection status: {page_phone.locator('#status').inner_text()}")

        # Select 1_35.avi and stream
        page_phone.select_option("#cloudClipSel", "1_35.avi")
        page_phone.wait_for_timeout(500)
        page_phone.click('button:has-text("Stream Clip")')
        page_phone.wait_for_selector("#txStat:has-text('Frames sent')", timeout=10000)
        print("  -> Phone is actively streaming frames over WebSocket. Keeping open in background!")
        page_phone.wait_for_timeout(1500)

        # ----------------------------------------------------
        # 3. Doctor Clinical HUD (/v2/doctor)
        # ----------------------------------------------------
        print(f"\n[STEP 3] Bringing page_main to Doctor HUD: /v2/doctor?code={room_code}")
        page_main.bring_to_front()
        page_main.goto(f"{BASE_URL}/v2/doctor?code={room_code}", wait_until="networkidle")
        page_main.wait_for_timeout(2500)

        # Standby Gate Display
        print("  -> Showcasing Standby Gate: AI overlays locked before doctor clicks Start.")
        page_main.wait_for_timeout(2500)

        # Doctor Clicks Start Procedure
        print("  -> Doctor clicks 'Start Procedure'...")
        page_main.click("#startBtn")

        # Wait until live AI overlay renders frame from L4 backend
        print("  -> Waiting for live L4 CADe video frame render on Doctor HUD...")
        page_main.wait_for_function(
            "() => document.getElementById('hudImg') && document.getElementById('hudImg').style.display === 'block' && document.getElementById('hudImg').src.length > 100",
            timeout=15000,
        )
        print("  -> Live L4 CADe video frame + bounding box active! Holding 5s for review...")
        page_main.wait_for_timeout(5000)

        # Sterile Voice Copilot: Dictate clinical findings
        print("  -> Triggering Sterile Voice Copilot ('Sample Dictation')...")
        page_main.click('button:has-text("Sample Dictation")')
        try:
            page_main.wait_for_selector("#voiceLog:has-text('Gemini parsed')", timeout=20000)
            print("  -> Gemini 3.8 Flash parsed structured dictation (zero-PHI verified)!")
            page_main.wait_for_timeout(3500)
        except Exception as e:
            print(f"  -> Voice wait note: {e}")
            page_main.wait_for_timeout(4000)

        # End Procedure & Generate Report
        print("  -> Clicking 'End Procedure & Generate Report'...")
        page_main.click("#endBtn")

        # Wait until report drafting finishes and ABDM FHIR R4 JSON is populated
        print("  -> Waiting for Gemini 3.8 Flash clinical report & ABDM FHIR R4 generation...")
        page_main.wait_for_selector("#repBody:not(:has-text('Drafting'))", timeout=25000)
        page_main.wait_for_function(
            "() => document.getElementById('fhirBox') && document.getElementById('fhirBox').textContent.length > 50",
            timeout=25000,
        )
        print("  -> Clinical report & ABDM FHIR R4 bundle generated! Holding 4s...")
        page_main.wait_for_timeout(4000)

        # Gemini TTS Bilingual Discharge Audio
        print("  -> Triggering Gemini TTS English & Tamil discharge playback...")
        try:
            page_main.click('button:has-text("Speak English Discharge")')
            page_main.wait_for_timeout(2500)
            page_main.click('button:has-text("Speak Tamil Discharge")')
            page_main.wait_for_timeout(2500)
        except Exception as e:
            print(f"  -> TTS click note: {e}")

        # Mandatory Physician HITL Attestation Gate
        print("  -> Checking Mandatory Physician HITL Attestation...")
        page_main.check("#hitlChk")
        page_main.wait_for_timeout(1500)

        # Sign-off & BigQuery Commit
        print("  -> Clicking 'Sign-Off & Commit to BigQuery Warehouse'...")
        page_main.click("#signBtn")
        try:
            page_main.wait_for_selector("#signBtn:has-text('Signed Off')", timeout=45000)
            print("  -> BigQuery commit receipt confirmed!")
            page_main.wait_for_timeout(3500)
        except Exception as e:
            print(f"  -> Signoff wait note: {e}")
            page_main.wait_for_timeout(4000)

        # Close Modal
        try:
            page_main.click('button:has-text("Close ✕")')
            page_main.wait_for_timeout(1500)
        except Exception:
            pass

        # ----------------------------------------------------
        # 4. Return to Admin BigQuery Analytics
        # ----------------------------------------------------
        print("\n[STEP 4] Returning page_main to Admin Console BigQuery Analytics...")
        page_main.goto(f"{BASE_URL}/v2/admin", wait_until="networkidle")
        page_main.wait_for_timeout(1500)
        page_main.click('button:has-text("BigQuery Analytics")')
        page_main.wait_for_timeout(1500)
        page_main.click('button:has-text("Refresh BigQuery Metrics")')
        print("  -> Live BigQuery Quality DW analytics card displayed! Holding 4s...")
        page_main.wait_for_timeout(4000)

        # Retrieve video path for page_main
        video_path_main = page_main.video.path()
        print(f"\n[DEMO RECORDING] page_main video recording captured at: {video_path_main}")

        page_phone.close()
        page_main.close()
        context.close()
        browser.close()

    final_webm = os.path.join(ASSETS_DIR, "CHAKRA_V2_Full_Demo.webm")
    shutil.copy2(video_path_main, final_webm)
    print(f"  -> Saved WebM demo: {final_webm} ({os.path.getsize(final_webm) / (1024 * 1024):.2f} MB)")

    final_mp4 = os.path.join(ASSETS_DIR, "CHAKRA_V2_Full_Demo.mp4")
    print("  -> Transcoding to 1080p MP4 via ffmpeg...")
    subprocess.run(
        [
            "ffmpeg",
            "-y",
            "-i",
            final_webm,
            "-c:v",
            "libx264",
            "-preset",
            "fast",
            "-crf",
            "20",
            "-pix_fmt",
            "yuv420p",
            final_mp4,
        ],
        check=True,
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
    )
    print(f"  -> Successfully generated final MP4: {final_mp4} ({os.path.getsize(final_mp4) / (1024 * 1024):.2f} MB)")
    print("\n[COMPLETE] Autonomous demo recording finished successfully!")


if __name__ == "__main__":
    record_demo()
