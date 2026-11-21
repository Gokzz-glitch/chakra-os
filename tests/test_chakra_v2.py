import base64
import concurrent.futures
import io
import os
import uuid
import pytest
from fastapi.testclient import TestClient
from clinical_pipeline import scrub_phi, evaluate_bbps, surveillance_years, parse_voice_note
import main

client = TestClient(main.app)

# Minimal valid 1x1 JPEG for testing frame submissions
TINY_JPEG_BYTES = b"\xff\xd8\xff\xe0\x00\x10JFIF\x00\x01\x01\x01\x00H\x00H\x00\x00\xff\xdb\x00C\x00\x08\x06\x06\x07\x06\x05\x08\x07\x07\x07\t\t\x08\n\x0c\x14\r\x0c\x0b\x0b\x0c\x19\x12\x13\x0f\x14\x1d\x1a\x1f\x1e\x1d\x1a\x1c\x1c $.' \",#\x1c\x1c(7),01444\x1f'9=82<.342\xff\xc0\x00\x0b\x08\x00\x01\x00\x01\x01\x01\x11\x00\xff\xc4\x00\x1f\x00\x00\x01\x05\x01\x01\x01\x01\x01\x01\x00\x00\x00\x00\x00\x00\x00\x00\x01\x02\x03\x04\x05\x06\x07\x08\t\n\x0b\xff\xda\x00\x08\x01\x01\x00\x00?\x00\xbf\x00\xff\xd9"
TINY_JPEG_B64 = "data:image/jpeg;base64," + base64.b64encode(TINY_JPEG_BYTES).decode()


def receive_json_with_timeout(ws, timeout=5.0):
    """Guards WebSocket receive_json with a strict timeout to prevent hangs."""
    executor = concurrent.futures.ThreadPoolExecutor(max_workers=1)
    future = executor.submit(ws.receive_json)
    try:
        return future.result(timeout=timeout)
    except concurrent.futures.TimeoutError:
        pytest.fail(f"WebSocket receive_json timed out after {timeout} seconds")
    finally:
        executor.shutdown(wait=False)


@pytest.fixture(autouse=True)
def mock_vision_l4_client(monkeypatch):
    """Mocks HTTP_CLIENT.post for chakra-vision to ensure fast, deterministic tests without internet stalls."""
    async def mock_post(url, *args, **kwargs):
        class MockResp:
            status_code = 200
            def json(self):
                return {
                    "device": "NVIDIA L4 (Mocked L4 Test)",
                    "latency_ms": 21.5,
                    "count": 1,
                    "detections": [{"box": [120, 80, 240, 210], "conf": 0.82, "class": "polyp"}],
                    "overlay_jpg_b64": base64.b64encode(TINY_JPEG_BYTES).decode(),
                }
            def raise_for_status(self):
                pass
        return MockResp()
    monkeypatch.setattr(main.HTTP_CLIENT, "post", mock_post)


def test_room_creation_6_digit_code_and_config():
    """Verify room creation generates 6-digit code and config is patchable."""
    res = client.post("/api/v2/rooms")
    assert res.status_code == 200
    data = res.json()
    code = data["code"]
    assert code.isdigit()
    assert len(code) == 6
    assert data["procedure_id"].startswith("PROC-")
    assert data["doctor_started"] is False
    assert data["phone_connected"] is False

    # Check GET room
    get_res = client.get(f"/api/v2/rooms/{code}")
    assert get_res.status_code == 200
    assert get_res.json()["code"] == code

    # Patch config
    patch_res = client.patch(
        f"/api/v2/rooms/{code}/config",
        json={
            "model": "yolovit_yolo",
            "conf": 0.55,
            "worker": "cloud_run_l4",
            "endoscopist_id": "DR-TEST-GOKUL",
            "patient_label": "PATIENT-X",
            "bbps_right": 3,
            "bbps_transverse": 3,
            "bbps_left": 3,
        },
    )
    assert patch_res.status_code == 200
    room_updated = patch_res.json()["room"]
    assert room_updated["conf"] == 0.55
    assert room_updated["endoscopist_id"] == "DR-TEST-GOKUL"

    # Non-existent room returns 404
    assert client.get("/api/v2/rooms/000000").status_code == 404


def test_standby_gate_no_overlay_before_doctor_start():
    """Strict Clinical Safety Gate: No overlay or live feed permitted until Doctor clicks Start."""
    room = client.post("/api/v2/rooms").json()
    code = room["code"]

    with client.websocket_connect(f"/ws/v2/{code}/doctor") as doc_ws:
        with client.websocket_connect(f"/ws/v2/{code}/phone") as phone_ws:
            # Drain initial phone_status message from doctor socket
            conn_msg = receive_json_with_timeout(doc_ws, timeout=5.0)
            assert conn_msg.get("type") == "phone_status"

            # Phone sends frame while doctor_started is False
            phone_ws.send_json({"type": "frame", "source": "phone_cam", "image_b64": TINY_JPEG_B64})

            # Doctor receives standby_heartbeat only, never hud_frame
            msg = receive_json_with_timeout(doc_ws, timeout=5.0)
            assert msg.get("type") == "standby_heartbeat"

            # Check room stats: frames_processed must be 0
            curr = client.get(f"/api/v2/rooms/{code}").json()
            assert curr["frames_processed"] == 0
            assert curr["doctor_started"] is False

            # Doctor explicitly clicks Start
            start_res = client.post(f"/api/v2/rooms/{code}/doctor-start")
            assert start_res.status_code == 200
            assert start_res.json()["doctor_started"] is True

            # Doctor receives procedure_started
            start_event = receive_json_with_timeout(doc_ws, timeout=5.0)
            assert start_event.get("type") == "procedure_started"

            # Phone sends frame now that procedure is ACTIVE
            phone_ws.send_json({"type": "frame", "source": "phone_cam", "image_b64": TINY_JPEG_B64})

            # Doctor receives live hud_frame (bounded check, max 3 reads)
            received_types = []
            for _ in range(3):
                event = receive_json_with_timeout(doc_ws, timeout=5.0)
                received_types.append(event.get("type"))
                if event.get("type") == "hud_frame":
                    assert "overlay_jpg_b64" in event
                    assert "latency_ms" in event
                    assert event.get("frames_processed") >= 1
                    break
            assert "hud_frame" in received_types


def test_l4_inference_admin_test_frame_and_depth1_dropping():
    """Verify L4 inference relay and depth-1 non-blocking frame dropping."""
    room = client.post("/api/v2/rooms").json()
    code = room["code"]

    # Direct model test on admin console
    file_payload = {"file": ("test_frame.jpg", io.BytesIO(TINY_JPEG_BYTES), "image/jpeg")}
    res = client.post(f"/api/v2/rooms/{code}/admin-test-frame", files=file_payload)
    assert res.status_code == 200
    inf = res.json()
    assert "device" in inf
    assert "latency_ms" in inf
    assert "overlay_jpg_b64" in inf
    assert "count" in inf

    # Test depth-1 drop behavior: when in_flight is True, incoming frame is dropped immediately
    main.ROOMS[code]["doctor_started"] = True
    main.ROOMS[code]["in_flight"] = True
    frames_before = main.ROOMS[code]["frames_processed"]

    with client.websocket_connect(f"/ws/v2/{code}/phone") as phone_ws:
        phone_ws.send_json({"type": "frame", "source": "live", "image_b64": TINY_JPEG_B64})
        # Frame should be dropped with zero increment
        assert main.ROOMS[code]["frames_processed"] == frames_before

    main.ROOMS[code]["in_flight"] = False


def test_gemini_voice_parsing_and_zero_phi_scrubbing():
    """Verify zero-PHI scrubbing on patient identifiers and Gemini voice extraction."""
    # Unit test scrub_phi
    raw_text = "Patient phone 9876543210 Aadhaar 1234-5678-9012, 7mm polyp in cecum"
    clean = scrub_phi(raw_text)
    assert "9876543210" not in clean
    assert "1234-5678-9012" not in clean
    assert "[PHONE-REDACTED]" in clean
    assert "[ID-REDACTED]" in clean

    # Clinical endpoint test
    room = client.post("/api/v2/rooms").json()
    code = room["code"]

    voice_res = client.post(
        f"/api/v2/rooms/{code}/voice-note",
        json={"transcript": "BBPS right 3 transverse 3 left 2, 7mm lesion in cecum, cold snare planned"},
    )
    assert voice_res.status_code == 200
    parsed_data = voice_res.json()
    assert parsed_data["ok"] is True
    assert "parsed" in parsed_data
    assert "bbps_scores" in parsed_data

    # Verify room state updated
    room_state = client.get(f"/api/v2/rooms/{code}").json()
    assert len(room_state["voice_notes"]) >= 1


def test_hitl_400_block_without_clinician_attestation():
    """Verify mandatory clinician HITL sign-off: BigQuery commit MUST fail if hitl_attested is false."""
    room = client.post("/api/v2/rooms").json()
    code = room["code"]

    # Starting and ending procedure to generate preliminary report
    client.post(f"/api/v2/rooms/{code}/doctor-start")
    end_res = client.post(f"/api/v2/rooms/{code}/end-report")
    assert end_res.status_code == 200
    assert end_res.json()["report"]["status"] == "PRELIMINARY"

    # Attempting sign-off without HITL attestation checkbox
    block_res = client.post(f"/api/v2/rooms/{code}/signoff", json={"hitl_attested": False})
    assert block_res.status_code == 400
    assert "Mandatory clinician HITL attestation required" in block_res.json()["detail"]

    # Verify on uninitialized room
    fresh_room = client.post("/api/v2/rooms").json()["code"]
    assert client.post(f"/api/v2/rooms/{fresh_room}/signoff", json={"hitl_attested": True}).status_code == 400


def test_bigquery_commit_and_analytics():
    """Verify successful HITL signoff commits to BigQuery warehouse and returns MCP analytics."""
    room = client.post("/api/v2/rooms").json()
    code = room["code"]

    client.post(f"/api/v2/rooms/{code}/doctor-start")
    client.post(f"/api/v2/rooms/{code}/end-report")

    # Sign-off with clinician HITL attestation True
    sign_res = client.post(f"/api/v2/rooms/{code}/signoff", json={"hitl_attested": True})
    assert sign_res.status_code == 200
    res_data = sign_res.json()
    report = res_data["report"]
    bq = res_data["bigquery"]

    assert report["status"] == "FINAL"
    assert report["pathology_status"] == "PENDING_HISTOPATHOLOGY"
    assert "abdm_fhir_r4" in report
    assert bq["mcp_endpoint"] == "https://bigquery.googleapis.com/mcp"
    assert "adr_metrics" in bq

    # Analytics route test
    ana_res = client.get("/api/v2/analytics")
    assert ana_res.status_code == 200
    assert "metrics" in ana_res.json()


def test_gcs_path_traversal_and_xss_security():
    """Verify path traversal and script injection attacks are blocked with 400/404."""
    malicious_paths = [
        "/api/v2/demo-videos/../../../etc/passwd",
        "/api/v2/demo-videos/..%2F..%2Fetc%2Fpasswd",
        "/api/v2/demo-videos/<script>alert(1)</script>",
        "/api/v2/demo-videos/evil..mp4",
        "/api/v2/demo-videos/sub/dir/test.mp4",
        "/api/v2/demo-videos/malicious.exe",
        "/api/v2/demo-videos/1_35.avi/../../etc/shadow",
    ]
    for path in malicious_paths:
        res = client.get(path)
        assert res.status_code in (400, 404), f"Path {path} returned unexpected status {res.status_code}"


def test_demo_videos_listing_and_range_206_streaming():
    """Verify demo video listing and Range/206 partial content streaming for MP4 and OpenCV fallback for AVI."""
    list_res = client.get("/api/v2/demo-videos")
    assert list_res.status_code == 200
    videos = list_res.json().get("videos", [])
    names = [v["name"] for v in videos]
    assert "ldpolyp_clip01.mp4" in names
    assert "1_35.avi" in names

    # Full MP4 stream (HTTP 200)
    full_res = client.get("/api/v2/demo-videos/ldpolyp_clip01.mp4")
    assert full_res.status_code == 200
    assert full_res.headers.get("accept-ranges") == "bytes"
    assert full_res.headers.get("content-type") == "video/mp4"
    size = len(full_res.content)
    assert size > 500 and size == int(full_res.headers["content-length"])
    assert full_res.content[4:8] == b"ftyp"

    # Partial Range stream (HTTP 206)
    range_res = client.get("/api/v2/demo-videos/ldpolyp_clip01.mp4", headers={"Range": "bytes=0-100"})
    assert range_res.status_code == 206
    assert range_res.headers.get("content-range") == f"bytes 0-100/{size}"
    assert range_res.headers.get("content-length") == "101"
    assert len(range_res.content) == 101

    # Suffix Range stream (last 500 bytes)
    suffix_res = client.get("/api/v2/demo-videos/ldpolyp_clip01.mp4", headers={"Range": "bytes=-500"})
    assert suffix_res.status_code == 206
    assert suffix_res.headers.get("content-length") == "500"
    assert suffix_res.content == full_res.content[-500:]
    extended = client.get("/api/v2/demo-videos/ldpolyp_clip01.mp4", headers={"Range": f"bytes={size-5}-{size+100}"})
    assert extended.status_code == 206 and extended.content == full_res.content[-5:]

    # Invalid range returns 416
    unsat_res = client.get("/api/v2/demo-videos/ldpolyp_clip01.mp4", headers={"Range": "bytes=999999-9999999"})
    assert unsat_res.status_code == 416

    # OpenCV frame extract fallback for 1_35.avi
    frame_res = client.get("/api/v2/demo-videos/1_35.avi/frame")
    assert frame_res.status_code == 200
    assert frame_res.headers.get("content-type") == "image/jpeg"
    assert frame_res.content.startswith(b"\xff\xd8")  # Valid JPEG magic bytes
    assert len(frame_res.content) > 1000

    # Query param extract fallback
    query_res = client.get("/api/v2/demo-videos/1_35.avi?extract=true")
    assert query_res.status_code == 200
    assert query_res.headers.get("content-type") == "image/jpeg"
    assert query_res.content.startswith(b"\xff\xd8")


def test_runs_enumeration_and_preseeded_history():
    """Verify stored backend runs enumeration, pre-seeded historical runs, and summary fields."""
    res = client.get("/api/v2/runs")
    assert res.status_code == 200
    data = res.json()
    assert "runs" in data
    runs_by_id = {r["run_id"]: r for r in data["runs"]}

    # Pre-seeded historical runs must exist
    for r_id in ["2abe559e", "d80e0cd7", "0273f6f9"]:
        assert r_id in runs_by_id, f"Pre-seeded run {r_id} missing from runs catalog"

    r_pra = runs_by_id["2abe559e"]
    assert r_pra["model"] == "pvt_pranet_v1"
    assert r_pra["frames_total"] == 944
    assert r_pra["frames_flagged"] == 932
    assert r_pra["fps"] == 37.97
    assert r_pra["review_status"] == "accepted"
    assert r_pra["fl_eligible"] is True
    assert r_pra["media_url"] == "/api/v2/demo-videos/ldpolyp_clip01.mp4"

    # Specific run lookup
    get_res = client.get("/api/v2/runs/2abe559e")
    assert get_res.status_code == 200
    run_detail = get_res.json()
    assert run_detail["run_id"] == "2abe559e"
    assert "flagged_evidence" in run_detail
    assert len(run_detail["flagged_evidence"]) >= 1

    # Non-existent run returns 404
    assert client.get("/api/v2/runs/nonexistent-run-id").status_code == 404


def test_runs_auto_append_and_clinician_fl_review():
    """Verify auto-appending of new runs on test-frame and clinician review marking FL-eligible."""
    room = client.post("/api/v2/rooms").json()
    code = room["code"]

    runs_before = len(client.get("/api/v2/runs").json()["runs"])

    unique_clip_name = f"test_auto_{uuid.uuid4().hex[:6]}.jpg"
    file_payload = {"file": (unique_clip_name, io.BytesIO(TINY_JPEG_BYTES), "image/jpeg")}
    tf_res = client.post(f"/api/v2/rooms/{code}/admin-test-frame", files=file_payload)
    assert tf_res.status_code == 200

    runs_after = client.get("/api/v2/runs").json()["runs"]
    assert len(runs_after) == runs_before + 1

    # Find the newly created run
    new_run = [r for r in runs_after if r.get("input_clip") == unique_clip_name][0]
    new_run_id = new_run["run_id"]
    assert new_run["review_status"] == "pending"
    assert new_run["fl_eligible"] is False

    # Review run with clinician accept decision and zero-PHI reason
    review_payload = {
        "decision": "accepted",
        "reason": "Clinician approved: Clear adenoma candidate, patient phone 9876543210 Aadhaar 1234-5678-9012",
        "reviewer_id": "DR-GOKUL-R",
    }
    rev_res = client.post(f"/api/v2/runs/{new_run_id}/review", json=review_payload)
    assert rev_res.status_code == 200
    rev_data = rev_res.json()["run"]
    assert rev_data["review_status"] == "accepted"
    assert rev_data["fl_eligible"] is True
    # Zero-PHI check: phone and aadhaar must be scrubbed
    assert "9876543210" not in rev_data["clinician_notes"]
    assert "1234-5678-9012" not in rev_data["clinician_notes"]


def test_export_fl_manifest():
    """Verify clean JSONL export containing only clinician-verified runs and GCS evidence URIs."""
    res = client.get("/api/v2/runs/export-fl-manifest")
    assert res.status_code == 200
    assert "application/x-jsonlines" in res.headers.get("content-type", "")

    lines = [line for line in res.text.strip().split("\n") if line.strip()]
    assert len(lines) >= 2  # At least 2abe559e and 0273f6f9

    import json
    for line in lines:
        item = json.loads(line)
        assert "run_id" in item
        assert "decision" in item
        assert item["decision"] in ("accepted", "dismissed")
        assert item["fl_eligible"] is True
        assert "gcs_media_uri" in item
        assert item["gcs_media_uri"].startswith("gs://")
        assert "evidence_uris" in item
        assert "anonymized_metadata" in item
        assert item["anonymized_metadata"]["zero_phi"] is True


def test_security_headers_present():
    """Verify HTTP security headers are injected on API responses."""
    res = client.get("/api/v2/catalog")
    assert res.status_code == 200
    assert res.headers.get("X-Content-Type-Options") == "nosniff"
    assert res.headers.get("X-Frame-Options") == "DENY"
    assert res.headers.get("Referrer-Policy") == "strict-origin-when-cross-origin"
    assert "max-age=63072000" in res.headers.get("Strict-Transport-Security", "")


def test_docs_disabled_in_production(monkeypatch):
    """Verify /docs, /redoc, and /openapi.json are disabled (404) in production."""
    monkeypatch.setenv("ENV", "production")
    for doc_path in ("/docs", "/redoc", "/openapi.json"):
        res = client.get(doc_path)
        assert res.status_code == 404


def test_oversized_transcript_input_rejection():
    """Verify transcripts exceeding 2000 characters are rejected with 400 or 422."""
    oversized = "A" * 2050
    room = client.post("/api/v2/rooms").json()
    code = room["code"]

    res = client.post(f"/api/v2/rooms/{code}/voice-note", json={"transcript": oversized})
    assert res.status_code in (400, 422)

    # Standalone endpoint rejection
    res2 = client.post("/api/v2/voice-parse", json={"transcript": oversized})
    assert res2.status_code in (400, 422)

    # Pipeline validation exception
    with pytest.raises(ValueError, match="exceeds maximum allowed length"):
        parse_voice_note(oversized)


def test_per_ip_rate_limiting_429(monkeypatch):
    """Verify per-IP rate limiting enforces maximum 30 requests/min and returns HTTP 429."""
    monkeypatch.setattr(main, "parse_voice_note", lambda t: {"clinical_note": t})
    test_ip = f"198.51.100.{uuid.uuid4().int % 200 + 10}"
    headers = {"X-Forwarded-For": test_ip}

    # Execute 30 valid requests
    for _ in range(30):
        r = client.post("/api/v2/voice-parse", json={"transcript": "BBPS 3 3 2"}, headers=headers)
        assert r.status_code == 200

    # 31st request must trigger 429
    r_blocked = client.post("/api/v2/voice-parse", json={"transcript": "BBPS 3 3 2"}, headers=headers)
    assert r_blocked.status_code == 429
    assert "Rate limit exceeded" in r_blocked.json()["detail"]
    assert r_blocked.headers.get("Retry-After") == "60"

