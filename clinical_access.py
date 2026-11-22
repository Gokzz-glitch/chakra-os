"""Access control for the single-hospital synthetic CHAKRA service."""

import asyncio
import hashlib
import hmac
import secrets
import logging
import re
import json
from functools import lru_cache
import os
from security_settings import TENANT, REGION, HEADERS, browser_origins, setting

from google.api_core.exceptions import NotFound
from google.auth.transport.requests import Request
from google.cloud import storage
from google.oauth2 import id_token
from starlette.datastructures import Headers
from starlette.responses import JSONResponse

AUDIENCE = os.environ.get(
    "IAP_AUDIENCE"
) or "/projects/{}/locations/{}/services/{}".format(
    setting("PROJECT_NUMBER", "local"), REGION, os.getenv("K_SERVICE", "chakra-os")
)
BUCKET = setting("CHAKRA_ACCESS_BUCKET", "development-access")
HOSPITAL = TENANT


@lru_cache(maxsize=1)
def bucket():
    return storage.Client().bucket(BUCKET)


def identify(token):
    claims = id_token.verify_token(
        token,
        Request(),
        audience=AUDIENCE,
        certs_url="https://www.gstatic.com/iap/verify/public_key",
    )
    if (
        claims.get("iss") != "https://cloud.google.com/iap"
        or not claims.get("sub")
        or not claims.get("email")
    ):
        raise ValueError("Invalid IAP identity")
    email = claims["email"].lower()
    key = hashlib.sha256(email.encode()).hexdigest()
    try:
        grant = json.loads(
            bucket().blob("accounts/" + key + ".json").download_as_bytes(timeout=5)
        )
    except NotFound:
        return None
    if (
        grant.get("email") != email
        or grant.get("hospital") != HOSPITAL
        or grant.get("role") not in {"clinician", "operator"}
    ):
        return None
    return email, grant["role"]


audit_key = setting("CHAKRA_AUDIT_HMAC_KEY", secrets.token_hex(32)).encode()
if len(audit_key) < 32:
    raise RuntimeError("CHAKRA_AUDIT_HMAC_KEY must contain at least 32 bytes")


def audit_ref(value):
    return hmac.new(
        audit_key, (TENANT + "/" + value).encode(), hashlib.sha256
    ).hexdigest()


audit_logger = logging.getLogger("clinical.audit")
audit_logger.setLevel(logging.INFO)
if not audit_logger.handlers:
    audit_handler = logging.StreamHandler()
    audit_handler.setFormatter(logging.Formatter("%(message)s"))
    audit_logger.addHandler(audit_handler)


class ClinicalAccess:
    def __init__(self, app):
        self.app = app

    async def __call__(self, scope, receive, send):
        kind = scope["type"]
        if kind not in {"http", "websocket"}:
            return await self.app(scope, receive, send)
        path = scope["path"].rstrip("/")
        audit_event = None
        for pattern, event in (
            (r"/api/v2/patients(?:/.*)?", "patient_access"),
            (r"/api/(?:signoff/[^/]+|v2/rooms/[^/]+/signoff)", "signoff"),
            (
                r"/api/v2/(?:runs/[^/]+/review|findings/[^/]+/pathology|rooms/[^/]+/finding-review)",
                "review",
            ),
            (r"/api/v2/runs/export-fl-manifest", "export"),
            (
                r"/api/v2/(?:rooms/[^/]+(?:/patient-consent)?|runs(?:/[^/]+)?)",
                "record_access",
            ),
        ):
            if re.fullmatch(pattern, path):
                audit_event = event
                break
        original_send = send

        async def send(message):
            if message["type"] == "http.response.start":
                from starlette.datastructures import MutableHeaders

                response_headers = MutableHeaders(scope=message)
                response_headers.update(HEADERS)
                if audit_event:
                    audit_logger.info(
                        json.dumps(
                            {
                                "event": audit_event,
                                "method": scope["method"],
                                "status": message["status"],
                                "role": scope.get("state", {}).get("role", "unknown"),
                                "actor_ref": audit_ref(
                                    scope.get("state", {}).get(
                                        "clinician_email", "unknown"
                                    )
                                ),
                                "resource_ref": audit_ref(path),
                            }
                        )
                    )
            await original_send(message)

        headers = Headers(scope=scope)
        token = headers.get("x-goog-iap-jwt-assertion")

        async def deny(status):
            if kind == "websocket":
                return await send({"type": "websocket.close", "code": 1008})
            return await JSONResponse(
                {"detail": "Access denied"},
                status_code=status,
                headers={"Cache-Control": "no-store"},
            )(scope, receive, send)

        if not token:
            return await deny(401)
        try:
            actor = await asyncio.to_thread(identify, token)
        except Exception:
            return await deny(403)
        if not actor:
            return await deny(403)
        email, role = actor
        scope.setdefault("state", {}).update(clinician_email=email, role=role)
        method = scope.get("method")
        if kind == "websocket" or method not in {"GET", "HEAD", "OPTIONS"}:
            origin = headers.get("origin")
            if len(headers.getlist("origin")) != 1 or origin not in browser_origins():
                return await deny(403)
        if kind == "websocket":
            expected = {"doctor": "clinician", "admin": "operator", "phone": "operator"}
            if expected.get(path.split("/")[-1]) != role:
                return await deny(403)
        else:
            clinical_read = path.startswith(
                ("/api/v2/patients/", "/v2/doctor/")
            ) or path in {
                "/v2/doctor",
                "/api/v2/patients",
                "/api/v2/runs/export-fl-manifest",
                "/api/v2/analytics",
            }
            operator_action = (
                (path == "/api/v2/rooms" and method == "POST")
                or re.fullmatch(
                    r"/api/v2/rooms/[^/]+/(?:config|admin-test-frame)", path
                )
                or (
                    method == "POST"
                    and re.fullmatch(r"/api/v2/rooms/[^/]+/patient-consent", path)
                )
            )
            if clinical_read:
                required = {"clinician"}
            elif operator_action or path in {"/v2/phone", "/api/v2/admin/test-frame"}:
                required = {"operator"}
            elif path == "/v2/admin":
                required = {"operator", "clinician"}
            elif method not in {"GET", "HEAD", "OPTIONS"}:
                required = {"clinician"}
            elif (
                path
                in {
                    "/",
                    "/logo.png",
                    "/api/warmup",
                    "/api/v2/catalog",
                    "/api/v2/session",
                    "/api/v2/evaluation/live",
                }
                or path.startswith(
                    (
                        "/static/",
                        "/v2/assets/",
                        "/api/v2/demo-videos/",
                        "/api/v2/rooms/",
                    )
                )
                or path == "/api/v2/demo-videos"
            ):
                required = {"operator", "clinician"}
            else:
                required = {"clinician"}
            if role not in required:
                return await deny(403)
        hospital = headers.get("x-hospital-id")
        if hospital and hospital != HOSPITAL:
            return await deny(403)
        scope["headers"] = [
            (k, v) for k, v in scope["headers"] if k.lower() != b"x-hospital-id"
        ] + [(b"x-hospital-id", HOSPITAL.encode())]
        if kind == "http":
            if method == "POST" and (
                path == "/api/analyze"
                or path.endswith(("/test-frame", "/admin-test-frame"))
            ):
                # Bound the entire multipart stream before Starlette parses or spools it.
                limit = 5 * 1024 * 1024 + 64 * 1024
                body = bytearray()
                while True:
                    part = await receive()
                    if part["type"] == "http.disconnect":
                        return
                    chunk = part.get("body", b"")
                    if len(body) + len(chunk) > limit:
                        return await deny(413)
                    body.extend(chunk)
                    if not part.get("more_body"):
                        break
                upstream_receive = receive

                async def receive():
                    nonlocal body
                    if body is None:
                        return await upstream_receive()
                    data, body = bytes(body), None
                    return {"type": "http.request", "body": data, "more_body": False}

            return await self.app(scope, receive, send)
        child = asyncio.create_task(self.app(scope, receive, send))
        try:
            while not child.done():
                done, _ = await asyncio.wait({child}, timeout=20)
                if done:
                    break
                try:
                    active = await asyncio.to_thread(identify, token)
                except Exception:
                    active = None
                if active != actor:
                    child.cancel()
                    await asyncio.gather(child, return_exceptions=True)
                    return await send({"type": "websocket.close", "code": 1008})
            await child
        finally:
            if not child.done():
                child.cancel()
                await asyncio.gather(child, return_exceptions=True)
