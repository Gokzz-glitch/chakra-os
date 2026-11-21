import base64
import concurrent.futures
import io
import os
import re
import pytest
from fastapi.testclient import TestClient
import main
from clinical_pipeline import scrub_phi, evaluate_bbps, surveillance_years

client = TestClient(main.app)

TINY_JPEG_BYTES = b"\xff\xd8\xff\xe0\x00\x10JFIF\x00\x01\x01\x01\x00H\x00H\x00\x00\xff\xdb\x00C\x00\x08\x06\x06\x07\x06\x05\x08\x07\x07\x07\t\t\x08\n\x0c\x14\r\x0c\x0b\x0b\x0c\x19\x12\x13\x0f\x14\x1d\x1a\x1f\x1e\x1d\x1a\x1c\x1c $.' \",#\x1c\x1c(7),01444\x1f'9=82<.342\xff\xc0\x00\x0b\x08\x00\x01\x00\x01\x01\x01\x11\x00\xff\xc4\x00\x1f\x00\x00\x01\x05\x01\x01\x01\x01\x01\x01\x00\x00\x00\x00\x00\x00\x00\x00\x01\x02\x03\x04\x05\x06\x07\x08\t\n\x0b\xff\xda\x00\x08\x01\x01\x00\x00?\x00\xbf\x00\xff\xd9"
TINY_JPEG_B64 = "data:image/jpeg;base64," + base64.b64encode(TINY_JPEG_BYTES).decode()


def receive_json_with_timeout(ws, timeout=5.0):
    executor = concurrent.futures.ThreadPoolExecutor(max_workers=1)
    future = executor.submit(ws.receive_json)
    try:
        return future.result(timeout=timeout)
    except concurrent.futures.TimeoutError:
        pytest.fail(f"WebSocket receive_json timed out after {timeout} seconds")
    finally:
        executor.shutdown(wait=False)


@pytest.fixture(autouse=True)
def mock_l4_client(monkeypatch):
    """Mocks HTTP_CLIENT.post for fast, deterministic L4 inference in test suite."""
    async def mock_post(url, *args, **kwargs):
        class MockResp:
            status_code = 200
            def json(self):
                return {
                    "device": "NVIDIA L4 (Mocked Test)",
                    "latency_ms": 22.0,
                    "count": 1,
                    "detections": [{"box": [100, 100, 200, 200], "conf": 0.85, "class": "polyp"}],
                    "overlay_jpg_b64": base64.b64encode(TINY_JPEG_BYTES).decode(),
                }
            def raise_for_status(self):
                pass
        return MockResp()
    monkeypatch.setattr(main.HTTP_CLIENT, "post", mock_post)


# ==========================================
# 1. UI Routes & Static Brand Logo
# ==========================================
def test_feature_01_ui_routes_and_static_logo():
    """Verify all UI pages, redirects, and official brand logo endpoint."""
    r_root = client.get("/", follow_redirects=False)
    assert r_root.status_code in (302, 307)
    assert r_root.headers.get("location") == "/v2/admin"

    r_admin = client.get("/v2/admin")
    assert r_admin.status_code == 200
    assert "CHAKRA" in r_admin.text
    assert "codeBox" in r_admin.text
    assert "qrInline" in r_admin.text
    assert "Patient History & Reconciliation" in r_admin.text

    r_phone = client.get("/v2/phone")
    assert r_phone.status_code == 200
    assert "Mobile Scope" in r_phone.text
    assert "codeIn" in r_phone.text
    assert "cloudClipSel" in r_phone.text

    r_doc = client.get("/v2/doctor")
    assert r_doc.status_code == 200
    assert "Doctor Clinical HUD" in r_doc.text
    assert "Doctor Gate Locked" in r_doc.text
    assert "startBtn" in r_doc.text

    r_logo = client.get("/logo.png")
    assert r_logo.status_code == 200
    assert r_logo.headers.get("content-type") == "image/png"
    assert len(r_logo.content) > 10000


# ==========================================
# 2. Warmup & System Health
# ==========================================
def test_feature_02_warmup_and_system_health():
    """Verify warmup endpoint returns health and hardware device."""
    res = client.get("/api/warmup")
    assert res.status_code == 200
    data = res.json()
    assert "status" in data


# ==========================================
# 3. Model Catalog & Registry
# ==========================================
def test_feature_03_model_catalog_registry():
    """Verify model catalog returns all 5 models and vision URL."""
    res = client.get("/api/v2/catalog")
    assert res.status_code == 200
    data = res.json()
    models = {m["id"]: m for m in data.get("models", [])}
    expected_models = ["yolovit_yolo", "pvt_pranet_v1", "chakranet", "sepnet", "rf_detr_s"]
    for mid in expected_models:
        assert mid in models, f"Model {mid} missing from catalog"
    assert models["yolovit_yolo"]["default"] is True
    assert "vision_url" in data


# ==========================================
# 4. Demo Videos Listing & Manifest
# ==========================================
def test_feature_04_demo_videos_listing():
    """Verify demo videos catalog lists staged GCS clips."""
    res = client.get("/api/v2/demo-videos")
    assert res.status_code == 200
    data = res.json()
    assert "videos" in data
    vnames = [v["name"] for v in data["videos"]]
    assert "ldpolyp_clip01.mp4" in vnames
    assert "sun_seg_seq01.mp4" in vnames
    assert "1_35.avi" in vnames


# ==========================================
# 5. RFC 7233 HTTP 206 Partial Content Streaming
# ==========================================
def test_feature_05_range_206_video_streaming():
    """Verify RFC 7233 HTTP 206 Range byte streaming for MP4 videos."""
    # Full stream (200)
    r_full = client.get("/api/v2/demo-videos/ldpolyp_clip01.mp4")
    assert r_full.status_code == 200
    assert r_full.headers.get("accept-ranges") == "bytes"
    assert r_full.headers.get("content-type") == "video/mp4"

    # Byte Range stream (206)
    r_range = client.get("/api/v2/demo-videos/ldpolyp_clip01.mp4", headers={"Range": "bytes=0-100"})
    assert r_range.status_code == 206
    assert "bytes 0-100/" in r_range.headers.get("content-range", "")
    assert r_range.headers.get("content-length") == "101"
    assert len(r_range.content) == 101

    # Suffix Range stream (last 200 bytes)
    r_suffix = client.get("/api/v2/demo-videos/ldpolyp_clip01.mp4", headers={"Range": "bytes=-200"})
    assert r_suffix.status_code == 206
    assert r_suffix.headers.get("content-length") == "200"

    # Out-of-bounds range (416)
    r_oob = client.get("/api/v2/demo-videos/ldpolyp_clip01.mp4", headers={"Range": "bytes=999999-9999999"})
    assert r_oob.status_code == 416


# ==========================================
# 6. OpenCV Frame Extraction Fallback for AVI
# ==========================================
def test_feature_06_opencv_frame_extraction_fallback():
    """Verify dynamic OpenCV frame extraction for non-native AVI containers."""
    for avi_name in ["1_35.avi", "1_1.avi", "1_11.avi"]:
        r_frame = client.get(f"/api/v2/demo-videos/{avi_name}/frame")
        assert r_frame.status_code == 200
        assert r_frame.headers.get("content-type") == "image/jpeg"
        assert r_frame.content.startswith(b"\xff\xd8")  # JPEG magic bytes
        assert len(r_frame.content) > 1000

    # Query param ?extract=true fallback
    r_extract = client.get("/api/v2/demo-videos/1_35.avi?extract=true")
    assert r_extract.status_code == 200
    assert r_extract.headers.get("content-type") == "image/jpeg"


# ==========================================
# 7. Security: Path Traversal & Injection Blocking
# ==========================================
def test_feature_07_path_traversal_and_injection_security():
    """Verify malicious traversal and injection paths are blocked with 400 or 404."""
    malicious_inputs = [
        "/api/v2/demo-videos/../../../etc/passwd",
        "/api/v2/demo-videos/..%2F..%2Fetc%2Fpasswd",
        "/api/v2/demo-videos/<script>alert(1)</script>",
        "/api/v2/demo-videos/evil..mp4",
        "/api/v2/demo-videos/sub/dir/test.mp4",
        "/api/v2/demo-videos/malicious.exe",
        "/api/v2/demo-videos/1_35.avi/../../etc/shadow",
    ]
    for path in malicious_inputs:
        res = client.get(path)
        assert res.status_code in (400, 404), f"Path {path} returned {res.status_code}"


# ==========================================
# 8. Room Creation & 6-Digit Pairing
# ==========================================
def test_feature_08_room_creation_and_pairing():
    """Verify room creation generates 6-digit numeric pairing code and procedure ID."""
    res = client.post("/api/v2/rooms")
    assert res.status_code == 200
    data = res.json()
    code = data["code"]
    assert code.isdigit()
    assert len(code) == 6
    assert data["procedure_id"].startswith("PROC-")
    assert data["doctor_started"] is False
    assert data["phone_connected"] is False

    # Get room
    r_get = client.get(f"/api/v2/rooms/{code}")
    assert r_get.status_code == 200
    assert r_get.json()["code"] == code

    # Non-existent room (404)
    assert client.get("/api/v2/rooms/000000").status_code == 404


# ==========================================
# 9. Room Configuration Patching
# ==========================================
def test_feature_09_room_config_patching():
    """Verify PATCH /api/v2/rooms/{code}/config updates model, threshold, worker."""
    room = client.post("/api/v2/rooms").json()
    code = room["code"]

    patch_res = client.patch(
        f"/api/v2/rooms/{code}/config",
        json={
            "model": "sepnet",
            "conf": 0.60,
            "worker": "cloud_run_l4",
            "endoscopist_id": "DR-PRIYA-S",
            "patient_label": "PATIENT-VERIFY",
            "bbps_right": 3,
            "bbps_transverse": 3,
            "bbps_left": 3,
        },
    )
    assert patch_res.status_code == 200
    updated = patch_res.json()["room"]
    assert updated["model"] == "sepnet"
    assert updated["conf"] == 0.60
    assert updated["endoscopist_id"] == "DR-PRIYA-S"


# ==========================================
# 10. Standby Gate & WebSocket Depth-1 Dropping
# ==========================================
def test_feature_10_standby_gate_and_depth1_websocket():
    """Strict Clinical Gate: No live feed or overlay allowed before Doctor Start."""
    room = client.post("/api/v2/rooms").json()
    code = room["code"]

    with client.websocket_connect(f"/ws/v2/{code}/doctor") as doc_ws:
        with client.websocket_connect(f"/ws/v2/{code}/phone") as phone_ws:
            # Phone connects -> doctor gets phone_status
            conn_msg = receive_json_with_timeout(doc_ws, timeout=5.0)
            assert conn_msg.get("type") == "phone_status"

            # Phone sends frame while doctor_started is False
            phone_ws.send_json({"type": "frame", "source": "phone_cam", "image_b64": TINY_JPEG_B64})

            # Doctor gets standby_heartbeat only, NEVER hud_frame
            standby_msg = receive_json_with_timeout(doc_ws, timeout=5.0)
            assert standby_msg.get("type") == "standby_heartbeat"

            # Check room stats: 0 frames processed
            assert client.get(f"/api/v2/rooms/{code}").json()["frames_processed"] == 0

            # Doctor explicitly starts procedure
            start_res = client.post(f"/api/v2/rooms/{code}/doctor-start")
            assert start_res.status_code == 200
            assert start_res.json()["doctor_started"] is True

            # Drain procedure_started
            start_event = receive_json_with_timeout(doc_ws, timeout=5.0)
            assert start_event.get("type") == "procedure_started"

            # Phone sends frame now that procedure is ACTIVE
            phone_ws.send_json({"type": "frame", "source": "phone_cam", "image_b64": TINY_JPEG_B64})

            # Doctor receives live hud_frame
            event = receive_json_with_timeout(doc_ws, timeout=5.0)
            while event.get("type") != "hud_frame":
                event = receive_json_with_timeout(doc_ws, timeout=5.0)
            assert event.get("type") == "hud_frame"
            assert "overlay_jpg_b64" in event
            assert "latency_ms" in event
            assert event.get("frames_processed") >= 1


# ==========================================
# 11. Direct Model L4 CADe Test
# ==========================================
def test_feature_11_direct_model_l4_test():
    """Verify direct image upload testing against active L4 model."""
    room = client.post("/api/v2/rooms").json()
    code = room["code"]

    file_payload = {"file": ("test.jpg", io.BytesIO(TINY_JPEG_BYTES), "image/jpeg")}
    res = client.post(f"/api/v2/rooms/{code}/admin-test-frame", files=file_payload)
    assert res.status_code == 200
    data = res.json()
    assert "device" in data
    assert "latency_ms" in data
    assert "count" in data
    assert "detections" in data
    assert "overlay_jpg_b64" in data


# ==========================================
# 12. Clinician Finding Review Decisions
# ==========================================
def test_feature_12_clinician_finding_review_decisions():
    """Verify clinician accept/dismiss decisions on candidate lesions."""
    room = client.post("/api/v2/rooms").json()
    code = room["code"]

    main.ROOMS[code]["findings"] = [
        {"id": "FND-01", "status": "accepted", "location": "Cecum", "conf": 0.88, "thumb_b64": "dGVzdA=="},
        {"id": "FND-02", "status": "accepted", "location": "Rectum", "conf": 0.75, "thumb_b64": "dGVzdA=="},
    ]

    # Dismiss FND-02
    res_dismiss = client.post(
        f"/api/v2/rooms/{code}/finding-review",
        json={"finding_id": "FND-02", "decision": "dismissed"},
    )
    assert res_dismiss.status_code == 200
    findings = {f["id"]: f for f in res_dismiss.json()["findings"]}
    assert findings["FND-02"]["status"] == "dismissed"
    assert findings["FND-01"]["status"] == "accepted"


# ==========================================
# 13. Zero-PHI Voice Dictation Scrubbing
# ==========================================
def test_feature_13_zero_phi_scrubbing_and_dictation():
    """Verify zero-PHI scrubbing on patient identifiers and structured extraction."""
    dirty_text = (
        "Patient: Ramesh Kumar, phone 9876543210, Aadhaar 1234-5678-9012, "
        "ABHA user123@abdm, MRN-99881, DOB: 14/05/1975. "
        "BBPS right 3 transverse 3 left 2, 8mm polyp in cecum"
    )
    clean = scrub_phi(dirty_text)
    assert "9876543210" not in clean
    assert "1234-5678-9012" not in clean
    assert "user123@abdm" not in clean
    assert "MRN-99881" not in clean
    assert "14/05/1975" not in clean
    assert "[PHONE-REDACTED]" in clean
    assert "[ID-REDACTED]" in clean
    assert "[ABHA-REDACTED]" in clean
    assert "[MRN-REDACTED]" in clean

    room = client.post("/api/v2/rooms").json()
    code = room["code"]
    res = client.post(
        f"/api/v2/rooms/{code}/voice-note",
        json={"transcript": "BBPS right 3 transverse 3 left 2, 7mm lesion in cecum"},
    )
    assert res.status_code == 200
    assert res.json()["ok"] is True
    assert "parsed" in res.json()


# ==========================================
# 14. Procedure Conclusion & Clinical Reporting
# ==========================================
def test_feature_14_end_procedure_and_clinical_report():
    """Verify procedure end generates preliminary report with SNOMED coding."""
    room = client.post("/api/v2/rooms").json()
    code = room["code"]

    client.post(f"/api/v2/rooms/{code}/doctor-start")
    end_res = client.post(f"/api/v2/rooms/{code}/end-report")
    assert end_res.status_code == 200
    report = end_res.json()["report"]
    assert report["status"] == "PRELIMINARY"
    assert report["pathology_status"] == "PENDING_HISTOPATHOLOGY"
    assert "abdm_fhir_r4" in report
    assert report["abdm_fhir_r4"]["resourceType"] == "DiagnosticReport"
    assert "narrative" in report


# ==========================================
# 15. Bilingual Patient Discharge Speech (Gemini TTS)
# ==========================================
def test_feature_15_bilingual_discharge_tts():
    """Verify Gemini TTS audio synthesis endpoint."""
    room = client.post("/api/v2/rooms").json()
    code = room["code"]

    tts_res = client.post(
        f"/api/v2/rooms/{code}/tts",
        json={"text": "Procedure completed successfully. Follow up in one week.", "voice_name": "Kore"},
    )
    assert tts_res.status_code == 200
    data = tts_res.json()
    assert "audio_b64" in data or "error" in data


# ==========================================
# 16. Mandatory Physician HITL Attestation Gate
# ==========================================
def test_feature_16_mandatory_hitl_attestation_gate():
    """Verify BigQuery commit is structurally blocked with HTTP 400 without HITL checkbox."""
    room = client.post("/api/v2/rooms").json()
    code = room["code"]

    client.post(f"/api/v2/rooms/{code}/doctor-start")
    client.post(f"/api/v2/rooms/{code}/end-report")

    # Attempt signoff without attestation (400)
    blocked_res = client.post(f"/api/v2/rooms/{code}/signoff", json={"hitl_attested": False})
    assert blocked_res.status_code == 400
    assert "Mandatory clinician HITL attestation required" in blocked_res.json()["detail"]


# ==========================================
# 17. BigQuery Warehouse Commit & MCP Analytics
# ==========================================
def test_feature_17_bigquery_commit_and_mcp_analytics():
    """Verify attested signoff commits to BigQuery and returns MCP analytics."""
    room = client.post("/api/v2/rooms").json()
    code = room["code"]

    client.post(f"/api/v2/rooms/{code}/doctor-start")
    client.post(f"/api/v2/rooms/{code}/end-report")

    # Attested signoff (200)
    sign_res = client.post(f"/api/v2/rooms/{code}/signoff", json={"hitl_attested": True})
    assert sign_res.status_code == 200
    assert sign_res.json()["report"]["status"] == "FINAL"
    assert sign_res.json()["bigquery"]["mcp_endpoint"] == "https://bigquery.googleapis.com/mcp"

    # Analytics route
    ana_res = client.get("/api/v2/analytics")
    assert ana_res.status_code == 200
    assert "metrics" in ana_res.json()


# ==========================================
# 18. Longitudinal Returning Patient History
# ==========================================
def test_feature_18_longitudinal_patient_history():
    """Verify returning patient history retrieval and evidence inspection."""
    res = client.get("/api/v2/patients/DEMO-PATIENT-01/history", headers={"X-Hospital-ID": "HOSP-CHENNAI-01"})
    assert res.status_code == 200
    data = res.json()
    assert data["patient_id"] == "DEMO-PATIENT-01"
    assert len(data["encounters"]) >= 1

    enc = data["encounters"][0]
    assert enc["procedure_id"] == "PROC-20250814-118240"
    assert len(enc["findings"]) >= 1
    fnd = enc["findings"][0]
    assert fnd["physician_decision"] == "accepted"
    assert fnd["pathology_status"] == "SIGNED"
    assert fnd["evidence_frame_url"].startswith("/api/v2/demo-videos/")


# ==========================================
# 19. Delayed Histopathology Reconciliation
# ==========================================
def test_feature_19_delayed_histopathology_reconciliation():
    """Verify delayed signed pathology report reconciles finding and updates surveillance."""
    res = client.post(
        "/api/v2/findings/FND-2025-01/pathology",
        json={
            "signed_by": "DR-PATH-RAMESH-V",
            "diagnosis": "Tubular Adenoma with Low-Grade Dysplasia",
            "dysplasia_grade": "Low-Grade",
            "margins": "Negative / Clear",
            "icd_o_code": "8211/0",
        },
    )
    assert res.status_code == 200
    data = res.json()
    assert data["ok"] is True
    assert data["reconciled"] is True
    assert data["earlier_decision_preserved"] == "accepted"
    assert "7-10 years" in data["finding"]["surveillance_recommendation"]


# ==========================================
# 20. Cross-Hospital Tenant Security Boundary
# ==========================================
def test_feature_20_cross_hospital_security_boundary():
    """Verify cross-hospital data boundary violation is blocked with HTTP 403."""
    res = client.get("/api/v2/patients/PATIENT-MUMBAI-99/history", headers={"X-Hospital-ID": "HOSP-CHENNAI-01"})
    assert res.status_code == 403
    assert "Cross-hospital data boundary violation" in res.json()["detail"]


# ==========================================
# 21. V1 Legacy Endpoints Backwards Compatibility
# ==========================================
def test_feature_21_v1_legacy_endpoints():
    """Verify backwards compatibility for legacy V1 single-image endpoints."""
    file_payload = {"file": ("v1_frame.jpg", io.BytesIO(TINY_JPEG_BYTES), "image/jpeg")}
    r_v1 = client.post(
        "/api/analyze",
        files=file_payload,
        data={"bbps_r": 3, "bbps_t": 3, "bbps_l": 2, "withdrawal_sec": 540, "endoscopist": "DR-GOKUL-R"},
    )
    assert r_v1.status_code == 200
    data = r_v1.json()
    assert "vision" in data
    assert "report" in data
    proc_id = data["report"]["procedure_id"]

    # V1 signoff
    r_v1_sign = client.post(f"/api/signoff/{proc_id}")
    assert r_v1_sign.status_code == 200
    assert r_v1_sign.json()["report"]["status"] == "FINAL"
