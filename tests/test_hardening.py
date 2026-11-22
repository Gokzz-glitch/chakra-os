"""Security and safety regressions using synthetic identities, frames and measurements."""

import ast
import base64
import hashlib
import json
import logging
import re
from html.parser import HTMLParser
from pathlib import Path
from unittest.mock import AsyncMock, patch

import pytest
from fastapi.testclient import TestClient
from starlette.requests import Request
from starlette.websockets import WebSocketDisconnect
from packaging.requirements import Requirement

import clinical_pipeline
import main
import security_settings
from evaluation import checkpoint_integrity
from evaluation.vendor import seg_infer

api = TestClient(main.app)
ORIGIN = "http://testserver"
JPEG = b"\xff\xd8\xff\xe0" + b"sample"
PNG = b"\x89PNG\r\n\x1a\n" + b"sample"


def auth(role):
    return {"origin": ORIGIN, "x-goog-iap-jwt-assertion": role}


def room():
    response = api.post("/api/v2/rooms", headers=auth("operator"))
    assert response.status_code == 200
    return response.json()["code"]


def clinician_post(code, action, **kwargs):
    return api.post(
        f"/api/v2/rooms/{code}/{action}", headers=auth("clinician"), **kwargs
    )


@pytest.mark.parametrize(
    "path",
    [
        "/api/v2/patients/DEMO-PATIENT-01/history",
        "/v2/doctor",
        "/v2/doctor/history",
        "/api/v2/runs/export-fl-manifest",
        "/api/v2/analytics",
    ],
)
@pytest.mark.parametrize("method", ["GET", "HEAD", "OPTIONS", "PATCH", "DELETE"])
def test_operator_cannot_enter_clinical_routes(method, path):
    assert api.request(method, path, headers=auth("operator")).status_code == 403
    if method == "GET":
        assert api.get(path, headers=auth("clinician")).is_success


@pytest.mark.parametrize(
    "path,method",
    [
        ("/v2/phone", "GET"),
        ("/api/v2/rooms", "POST"),
        ("/api/v2/rooms/000000/config", "PATCH"),
        ("/api/v2/admin/test-frame", "POST"),
    ],
)
def test_operator_actions_require_operator_role(path, method):
    assert api.request(method, path, headers=auth("clinician")).status_code == 403


@pytest.mark.parametrize("origin", [None, "null", "https://other.invalid"])
def test_origin_required_for_http_and_socket(origin):
    headers = {"x-goog-iap-jwt-assertion": "operator"}
    if origin is not None:
        headers["origin"] = origin
    assert api.post("/api/v2/rooms", headers=headers).status_code == 403
    with pytest.raises(WebSocketDisconnect) as exc:
        with api.websocket_connect(f"/ws/v2/{room()}/phone", headers=headers):
            pass
    assert exc.value.code == 1008


def test_production_cors_filters_local(monkeypatch):
    monkeypatch.setattr(security_settings, "PRODUCTION", True)
    monkeypatch.setenv(
        "ALLOWED_HOSTS",
        "http://localhost:8080,http://127.0.0.1,http://testserver,https://clinic.example",
    )
    assert security_settings.browser_origins() == {"https://clinic.example"}


@pytest.mark.parametrize(
    "path", ["/v2/admin", "/v2/doctor", "/v2/phone", "/v1", "/api/v2/catalog"]
)
def test_no_store_and_strict_csp_on_clinical_and_denial_responses(path):
    for response in [
        api.get(path),
        api.get(
            path,
            headers=auth(
                "operator" if path.endswith(("admin", "phone")) else "clinician"
            ),
        ),
    ]:
        assert response.headers["cache-control"] == "no-store, max-age=0"
        assert response.headers["permissions-policy"]
        csp = response.headers["content-security-policy"]
        assert "'unsafe-inline'" not in csp and "'unsafe-eval'" not in csp
        for directive in (
            "default-src 'self'",
            "object-src 'none'",
            "frame-ancestors 'none'",
            "base-uri 'self'",
        ):
            assert directive in csp


def test_proxy_fallback_only_trusts_immediate_peer(monkeypatch):
    req = Request(
        {
            "type": "http",
            "client": ("192.0.2.1", 2345),
            "headers": [(b"x-forwarded-for", b"192.0.2.3, 192.0.2.2")],
        }
    )
    assert main.rate_identity(req) == "192.0.2.1"
    monkeypatch.setenv("TRUSTED_PROXY_IPS", "192.0.2.1")
    assert main.rate_identity(req) == "192.0.2.2"
    req.state.clinician_email = "test@example.invalid"
    assert main.rate_identity(req) == req.state.clinician_email


@pytest.mark.parametrize(
    "method,path,role",
    [
        ("GET", "/api/v2/patients/DEMO-PATIENT-01/history", "clinician"),
        ("POST", "/api/v2/rooms", "operator"),
        ("POST", "/api/v2/rooms/{code}/signoff", "clinician"),
        ("POST", "/api/analyze", "clinician"),
        ("POST", "/api/v2/admin/test-frame", "operator"),
        ("POST", "/api/v2/rooms/{code}/admin-test-frame", "operator"),
    ],
)
def test_metered_routes_cannot_be_reset_by_forwarded_header(method, path, role):
    path = path.format(code=room())
    main.request_windows.clear()
    for i in range(31):
        response = api.request(
            method, path, headers={**auth(role), "X-Forwarded-For": f"192.0.2.{i}"}
        )
        assert (response.status_code == 429) == (i == 30)


def test_pairing_expiry_and_lockout(monkeypatch):
    with patch.object(main.secrets, "randbelow", return_value=234567):
        code = room()
    assert code == "334567"
    assert 899 < main.ROOMS[code]["pairing_expires_at"] - main.time.monotonic() <= 900
    main.ROOMS[code]["pairing_expires_at"] -= 901
    assert api.get(f"/api/v2/rooms/{code}", headers=auth("operator")).status_code == 404
    with pytest.raises(WebSocketDisconnect):
        with api.websocket_connect(f"/ws/v2/{code}/phone", headers=auth("operator")):
            pass
    valid = room()
    main.pairing_failures.clear()
    for _ in range(5):
        assert (
            api.get("/api/v2/rooms/invalid", headers=auth("operator")).status_code
            == 404
        )
    assert (
        api.get(f"/api/v2/rooms/{valid}", headers=auth("operator")).status_code == 429
    )
    assert (
        api.get(f"/api/v2/rooms/{valid}", headers=auth("clinician")).status_code == 200
    )


@pytest.mark.parametrize(
    "target,role",
    [
        ("/api/v2/rooms/{code}/admin-test-frame", "operator"),
        ("/api/v2/admin/test-frame", "operator"),
        ("/api/analyze", "clinician"),
    ],
)
def test_upload_bounds_and_signature(target, role):
    url = target.format(code=room())
    for payload, status in [(b"text", 415), (JPEG + b"0" * main.MAX_IMAGE_BYTES, 413)]:
        assert (
            api.post(
                url,
                headers=auth(role),
                data={
                    "bbps_r": 1,
                    "bbps_t": 1,
                    "bbps_l": 1,
                    "withdrawal_sec": 10,
                    "endoscopist": "synthetic",
                },
                files={"file": ("frame.png", payload, "image/png")},
            ).status_code
            == status
        )
    assert main.validate_image(PNG) == PNG
    assert main.safe_filename(r"C:\sample\../case<1>.jpg") == "case_1_.jpg"


@pytest.mark.parametrize(
    "encoded",
    [base64.b64encode(b"text").decode(), "!", "X" * (7 * 1024 * 1024)],
    ids=["invalid-image", "invalid-base64", "oversize"],
)
def test_bad_socket_frame_closes_even_in_standby(encoded):
    with api.websocket_connect(
        f"/ws/v2/{room()}/phone", headers=auth("operator")
    ) as socket:
        socket.send_json({"type": "frame", "image_b64": encoded})
        assert socket.receive()["type"] == "websocket.close"


def test_measurements_clock_and_attestation(monkeypatch):
    code = room()
    state = main.ROOMS[code]
    assert set(state["bbps_scores"].values()) == {None} and state["max_mm"] is None
    assert clinician_post(code, "end-report").status_code == 409
    invalid = {"right": 4, "left": 2, "transverse": 1, "max_mm": 0}
    assert clinician_post(code, "measurements", json=invalid).status_code == 422
    assert clinician_post(code, "measurements", json=dict(invalid, right=0)).is_success
    assert clinician_post(code, "end-report").json()["withdrawal_sec"] is None
    assert (
        clinician_post(code, "signoff", json={"hitl_attested": True}).status_code == 409
    )
    assert api.post("/api/signoff/sample", headers=auth("clinician")).status_code == 422
    assert (
        api.post(
            "/api/signoff/sample",
            headers=auth("clinician"),
            json={"hitl_attested": False},
        ).status_code
        == 400
    )


def test_backend_timeout_surfaces_on_hud(monkeypatch, caplog):
    import asyncio

    code = room()
    main.ROOMS[code].update(doctor_started=True, in_flight=True)
    monkeypatch.setattr(main.HTTP_CLIENT, "post", AsyncMock(side_effect=TimeoutError()))
    broadcast = AsyncMock()
    monkeypatch.setattr(main, "_broadcast", broadcast)
    asyncio.run(
        main._process_phone_frame(code, {"image_b64": base64.b64encode(JPEG).decode()})
    )
    roles, event = broadcast.await_args.args[1:]
    assert "doctor" in roles and event["type"] == "ai_degraded" and "count" not in event
    assert (
        not main.ROOMS[code]["in_flight"] and main.ROOMS[code]["frames_processed"] == 0
    )
    assert any(
        json.loads(r.message)["event"] == "ai_degraded"
        for r in caplog.records
        if r.name == "clinical"
    )


def test_unknown_patient_does_not_mutate_registry(caplog):
    before = set(main.PATIENT_REGISTRY)
    with caplog.at_level(logging.INFO, logger="clinical.audit"):
        response = api.get(
            "/api/v2/patients/unknown-synthetic/history", headers=auth("clinician")
        )
        assert response.status_code == 404
    assert set(main.PATIENT_REGISTRY) == before
    records = [
        json.loads(r.message) for r in caplog.records if r.name == "clinical.audit"
    ]
    (entry,) = records
    assert (
        entry["event"] == "patient_access"
        and entry["status"] == 404
        and entry["role"] == "clinician"
    )
    assert re.fullmatch(r"[0-9a-f]{64}", entry["actor_ref"])
    assert re.fullmatch(r"[0-9a-f]{64}", entry["resource_ref"])
    assert "unknown-synthetic" not in str(entry) and "@" not in str(entry)


def test_preserve_initial_pathology_and_every_addendum():
    path = "/api/v2/findings/FND-2025-01/pathology"
    for n in range(2):
        r = api.post(
            path,
            headers=auth("clinician"),
            json={"diagnosis": f"synthetic amendment {n}"},
        )
        assert r.is_success
        f = r.json()["finding"]
        assert (
            f["pathology_result"]["diagnosis"]
            == "Tubular Adenoma with Low-Grade Dysplasia"
        )
        assert [a["diagnosis"] for a in f["pathology_addenda"]] == [
            f"synthetic amendment {i}" for i in range(n + 1)
        ]
        assert f["pathology_addenda"][-1]["signed_by"] == "clinician@example.invalid"


@pytest.mark.parametrize(
    "identifier",
    [
        "test.person@example.invalid",
        "123-45-6789",
        "SSN 123456789",
        "passport 9988776655",
        "943 476 5919",
        "123.456.789-09",
        "passport no. A12345678",
        "DOB: 2001-03-04",
        "DOB: 04/03/2001",
        "date of birth March 4, 2001",
        "born 4 March 2001",
    ],
)
def test_identifier_scrubbing(identifier):
    result = clinical_pipeline.scrub_phi(identifier)
    assert "[REDACTED]" in result or "[DOB-REDACTED]" in result
    assert identifier.split()[-1] not in result


def test_wav_response_and_unavailable_audio(monkeypatch):
    wav = b"RIFF" + bytes(4) + b"WAVE"
    monkeypatch.setattr(
        main,
        "synthesize_discharge_audio",
        lambda *args: {"audio_b64": base64.b64encode(wav).decode()},
    )
    response = api.post(
        "/api/v2/tts", headers=auth("clinician"), json={"text": "synthetic"}
    )
    assert response.content == wav and response.headers["content-type"] == "audio/wav"
    monkeypatch.setattr(
        main, "synthesize_discharge_audio", lambda *args: {"error": "offline"}
    )
    assert (
        api.post(
            "/api/v2/tts", headers=auth("clinician"), json={"text": "test"}
        ).status_code
        == 503
    )


def test_hash_gate(tmp_path, monkeypatch):
    weights = tmp_path / "sample"
    weights.write_bytes(b"synthetic")
    for key in ("unknown", "sepnet"):
        with pytest.raises(ValueError):
            checkpoint_integrity.verify_checkpoint(key, weights)
    digest = hashlib.sha256(weights.read_bytes()).hexdigest()
    (tmp_path / "checkpoint_hashes.json").write_text(json.dumps({"test": digest}))
    monkeypatch.setattr(checkpoint_integrity, "__file__", str(tmp_path / "gate.py"))
    checkpoint_integrity.verify_checkpoint("test", weights)
    weights.write_bytes(b"changed")
    with pytest.raises(ValueError):
        checkpoint_integrity.verify_checkpoint("test", weights)


def test_no_pickle_retry(monkeypatch):
    import sys
    from unittest.mock import Mock

    torch = Mock()
    torch.load.side_effect = ValueError("unsupported checkpoint")
    monkeypatch.setitem(sys.modules, "torch", torch)
    with pytest.raises(ValueError):
        seg_infer.load_weights(None, "fixture", "cpu")
    torch.load.assert_called_once_with("fixture", map_location="cpu", weights_only=True)


def test_container_and_sbom_match_manifest():
    docker = Path("Dockerfile").read_text()
    assert "USER appuser" in docker and "useradd" in docker
    requirements = [
        Requirement(row)
        for row in Path("requirements.txt").read_text().splitlines()
        if row.strip()
    ]
    bom = json.loads(Path("sbom.json").read_text())
    assert bom["bomFormat"] == "CycloneDX"
    inventory = {(c["name"], c["version"]) for c in bom["components"]}
    for req in requirements:
        (spec,) = list(req.specifier)
        assert spec.operator == "==" and (req.name, spec.version) in inventory
    worker = ast.parse(Path("evaluation/worker.py").read_text())
    run = next(
        fn for fn in worker.body if isinstance(fn, ast.FunctionDef) and fn.name == "run"
    )
    calls = {
        ast.unparse(node.func): node.lineno
        for node in ast.walk(run)
        if isinstance(node, ast.Call)
    }
    assert calls["verify_checkpoint"] < min(
        calls["YOLO"], calls["seg_infer.load_weights"]
    )


class Markup(HTMLParser):
    def handle_starttag(self, tag, attrs):
        attrs = dict(attrs)
        assert not any(key.startswith("on") for key in attrs)
        assert "style" not in attrs
        if tag == "script":
            url = attrs["src"]
            assert url.startswith(("/static/", "/v2/assets/"))
            assert api.get(url, headers=auth("clinician")).is_success


@pytest.mark.parametrize("page", ["admin", "doctor", "phone", "index_v1"])
def test_markup_has_only_local_external_scripts(page):
    html = Path(page + ".html").read_text(encoding="utf8")
    Markup().feed(html)
    if page != "index_v1":
        assert Path("templates", page + ".html").read_text(encoding="utf8") == html
    for f in Path("static").glob(page + "*.js"):
        js = f.read_text(encoding="utf-8-sig")
        assert not re.search(
            r"innerHTML\s*=|insertAdjacentHTML|api\.qrserver\.com|cdnjs\.cloudflare\.com",
            js,
        )


@pytest.mark.parametrize("stored_tenant", ["another-hospital", None])
def test_cached_and_uncached_runs_stay_within_tenant(stored_tenant):
    run_id = "other-synthetic-run"
    record = {"run_id": run_id, "hospital_id": stored_tenant, "fl_eligible": True}
    obj = (
        main.storage.Client()
        .bucket(main.GCS_BUCKET)
        .blob("run_logs/" + run_id + ".json")
    )
    obj.exists.return_value = True
    obj.download_as_text.return_value = json.dumps(record)
    path = "/api/v2/runs/" + run_id
    assert api.get(path, headers=auth("clinician")).status_code == 404
    assert run_id not in main.RUN_LOGS
    main.RUN_LOGS[run_id] = record
    assert api.get(path, headers=auth("clinician")).status_code == 404
    assert run_id not in api.get("/api/v2/runs", headers=auth("clinician")).text
    assert (
        run_id
        not in api.get(
            "/api/v2/runs/export-fl-manifest", headers=auth("clinician")
        ).text
    )
    assert (
        api.post(
            path + "/review", headers=auth("clinician"), json={"decision": "accepted"}
        ).status_code
        == 404
    )


def test_pathology_retries_readback_and_storage_failure(monkeypatch):
    path = "/api/v2/findings/FND-2025-01/pathology"
    for _ in range(2):
        assert api.post(
            path, headers=auth("clinician"), json={"diagnosis": "Synthetic addendum"}
        ).is_success
    patient = api.get(
        "/api/v2/patients/DEMO-PATIENT-01/history", headers=auth("clinician")
    ).json()
    assert len(patient["encounters"][0]["findings"][0]["pathology_addenda"]) == 1
    assert (
        "pathology_addenda"
        not in main.PATIENT_REGISTRY["DEMO-PATIENT-01"]["encounters"][0]["findings"][0]
    )
    monkeypatch.setattr(main.pathology_journal, "bucket", lambda: None)
    assert (
        api.post(
            path, headers=auth("clinician"), json={"diagnosis": "Another entry"}
        ).status_code
        == 503
    )


def test_audit_signoff_review_export_denials_and_success(caplog):
    with caplog.at_level(logging.INFO, logger="clinical.audit"):
        api.post(
            "/api/signoff/test",
            headers=auth("clinician"),
            json={"hitl_attested": False},
        )
        api.post(
            "/api/v2/runs/test/review",
            headers=auth("operator"),
            json={"decision": "accepted"},
        )
        api.get("/api/v2/runs/export-fl-manifest", headers=auth("clinician"))
    events = [
        json.loads(r.message) for r in caplog.records if r.name == "clinical.audit"
    ]
    assert [(e["event"], e["status"]) for e in events] == [
        ("signoff", 400),
        ("review", 403),
        ("export", 200),
    ]
    assert all("@" not in str(e) and "/api/" not in str(e) for e in events)


def test_failed_frame_test_does_not_create_negative_run(monkeypatch):
    code = room()
    before = set(main.RUN_LOGS)
    monkeypatch.setattr(main.HTTP_CLIENT, "post", AsyncMock(side_effect=TimeoutError()))
    for url in ["/api/v2/admin/test-frame", f"/api/v2/rooms/{code}/admin-test-frame"]:
        assert (
            api.post(
                url,
                headers=auth("operator"),
                files={"file": ("frame.jpg", JPEG, "image/jpeg")},
            ).status_code
            == 503
        )
    assert set(main.RUN_LOGS) == before


def test_operator_room_view_excludes_clinical_record():
    code = room()
    main.ROOMS[code]["voice_notes"].append("synthetic clinician note")
    for result in (
        api.get(f"/api/v2/rooms/{code}", headers=auth("operator")).json(),
        api.patch(
            f"/api/v2/rooms/{code}/config", headers=auth("operator"), json={}
        ).json()["room"],
    ):
        assert (
            "voice_notes" not in result
            and "findings" not in result
            and "last_payload" not in result
        )


def test_recent_clock_is_frozen_on_repeated_report(monkeypatch):
    code = room()
    clinician_post(
        code, "measurements", json={"right": 2, "left": 2, "transverse": 2, "max_mm": 0}
    )
    clinician_post(code, "doctor-start")
    main.ROOMS[code]["started_ts"] -= 20
    elapsed = clinician_post(code, "end-report").json()["withdrawal_sec"]
    main.ROOMS[code]["started_ts"] -= 100
    assert (
        elapsed >= 20
        and clinician_post(code, "end-report").json()["withdrawal_sec"] == elapsed
    )


def test_shared_security_windows_enforce_and_expire(monkeypatch):
    from google.api_core.exceptions import NotFound, PreconditionFailed
    import security_windows
    import json

    backend = {}

    class Blob:
        def __init__(self, name):
            self.name = name

        def reload(self, **kwargs):
            if self.name not in backend:
                raise NotFound("missing")
            self.generation = backend[self.name][0]

        def download_as_bytes(self, if_generation_match, **kwargs):
            assert if_generation_match == backend[self.name][0]
            return backend[self.name][1]

        def upload_from_string(self, value, if_generation_match, **kwargs):
            generation = backend.get(self.name, (0, None))[0]
            if if_generation_match != generation:
                raise PreconditionFailed("write conflict")
            backend[self.name] = (generation + 1, value)

    from unittest.mock import Mock

    client = Mock()
    client.bucket.return_value.blob = Blob
    monkeypatch.setattr(security_windows.storage, "Client", lambda **kwargs: client)
    monkeypatch.setattr(security_windows.time, "time", lambda: 10)
    for _ in range(2):
        assert not security_windows.blocked("requests", "synthetic-user", 60, 2)
    assert security_windows.blocked("requests", "synthetic-user", 60, 2)
    assert not security_windows.blocked("requests", "different-user", 60, 2)
    assert not security_windows.blocked("pairing", "synthetic-user", 900, 5, False)
    assert all("user" not in name for name in backend)
    monkeypatch.setattr(security_windows.time, "time", lambda: 71)
    assert not security_windows.blocked("requests", "synthetic-user", 60, 2)


def test_production_quota_storage_failure_denies(monkeypatch):
    monkeypatch.setattr(main, "is_prod", True)

    def unavailable(*args):
        raise OSError("offline")

    monkeypatch.setattr(main.security_windows, "blocked", unavailable)
    assert api.post("/api/v2/rooms", headers=auth("operator")).status_code == 429


def test_role_verification_uses_configured_tenant_and_iap(monkeypatch):
    import clinical_access

    # Autouse fixtures replace identify; exercise the unmocked verifier from its defining module.
    import importlib.util

    spec = importlib.util.spec_from_file_location(
        "access_verifier_under_test", clinical_access.__file__
    )
    verifier = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(verifier)
    email = "reviewer@example.invalid"
    token = {"sub": "123", "iss": "https://cloud.google.com/iap", "email": email}

    def verified(*args, **kwargs):
        assert kwargs["audience"] == verifier.AUDIENCE
        return token

    monkeypatch.setattr(verifier.id_token, "verify_token", verified)
    from unittest.mock import Mock

    storage = Mock()
    monkeypatch.setattr(verifier, "bucket", lambda: storage)
    for tenant, expected in [
        (verifier.HOSPITAL, (email, "clinician")),
        ("foreign", None),
    ]:
        storage.blob.return_value.download_as_bytes.return_value = json.dumps(
            {"email": email, "role": "clinician", "hospital": tenant}
        ).encode()
        assert verifier.identify("synthetic-assertion") == expected
    token["iss"] = "invalid"
    with pytest.raises(ValueError):
        verifier.identify("synthetic-assertion")


def test_required_production_settings(monkeypatch):
    monkeypatch.setenv("ENV", "production")
    monkeypatch.delenv("CHAKRA_TENANT_ID", raising=False)
    with pytest.raises(RuntimeError, match="CHAKRA_TENANT_ID"):
        security_settings.setting("CHAKRA_TENANT_ID", "development")


def test_frame_upload_persists_sanitized_basename(monkeypatch):
    from unittest.mock import Mock

    response = Mock()
    response.json.return_value = {"count": 0, "detections": [], "latency_ms": 1}
    monkeypatch.setattr(main.HTTP_CLIENT, "post", AsyncMock(return_value=response))
    code = room()
    previous = set(main.RUN_LOGS)
    result = api.post(
        f"/api/v2/rooms/{code}/admin-test-frame",
        headers=auth("operator"),
        files={"file": ("../sample@image.jpg", JPEG, "image/jpeg")},
    )
    assert result.is_success
    (new_id,) = set(main.RUN_LOGS) - previous
    assert main.RUN_LOGS[new_id]["input_clip"] == "sample_image.jpg"


def test_bigquery_analytics_uses_deployment_tenant_and_region():
    client = clinical_pipeline.bigquery.Client()
    result = api.get("/api/v2/analytics", headers=auth("clinician"))
    assert result.is_success
    (sql,) = client.query.call_args.args
    config = client.query.call_args.kwargs["job_config"]
    (tenant,) = config.query_parameters
    assert "WHERE hospital_id = @tenant" in sql
    assert (tenant.name, tenant.value) == ("tenant", security_settings.TENANT)
    assert client.create_dataset.call_args.args[0].location == security_settings.REGION
