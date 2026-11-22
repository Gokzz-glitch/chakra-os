"""Access control for the single-hospital synthetic CHAKRA service."""
import asyncio
import hashlib
import json
from functools import lru_cache
from urllib.parse import urlsplit

from google.api_core.exceptions import NotFound
from google.auth.transport.requests import Request
from google.cloud import storage
from google.oauth2 import id_token
from starlette.datastructures import Headers
from starlette.responses import JSONResponse

AUDIENCE = "/projects/219670109842/locations/asia-south1/services/chakra-os"
BUCKET = "girpolypposframesrealcolon-chakra-access"
HOSPITAL = "HOSP-CHENNAI-01"


@lru_cache(maxsize=1)
def bucket():
    return storage.Client().bucket(BUCKET)


def identify(token):
    claims = id_token.verify_token(token, Request(), audience=AUDIENCE,
                                   certs_url="https://www.gstatic.com/iap/verify/public_key")
    if claims.get("iss") != "https://cloud.google.com/iap" or not claims.get("sub") or not claims.get("email"):
        raise ValueError("Invalid IAP identity")
    email = claims["email"].lower()
    key = hashlib.sha256(email.encode()).hexdigest()
    try:
        grant = json.loads(bucket().blob("accounts/" + key + ".json").download_as_bytes(timeout=5))
    except NotFound:
        return None
    if grant.get("email") != email or grant.get("hospital") != HOSPITAL or grant.get("role") not in {"clinician", "operator"}:
        return None
    return email, grant["role"]


class ClinicalAccess:
    def __init__(self, app):
        self.app = app

    async def __call__(self, scope, receive, send):
        kind = scope["type"]
        if kind not in {"http", "websocket"}:
            return await self.app(scope, receive, send)
        headers = Headers(scope=scope)
        token = headers.get("x-goog-iap-jwt-assertion")
        async def deny(status):
            if kind == "websocket":
                return await send({"type": "websocket.close", "code": 1008})
            return await JSONResponse({"detail": "Access denied"}, status_code=status,
                                      headers={"Cache-Control": "no-store"})(scope, receive, send)
        if not token:
            return await deny(401)
        try:
            actor = await asyncio.to_thread(identify, token)
        except Exception:
            return await deny(403)
        if not actor:
            return await deny(403)
        email, role = actor
        path = scope["path"].rstrip("/")
        method = scope.get("method")
        if kind == "websocket" or method not in {"GET","HEAD","OPTIONS"}:
            origin = headers.get("origin")
            if origin and (urlsplit(origin).netloc != headers.get("host") or urlsplit(origin).scheme != "https"):
                return await deny(403)
        if kind == "websocket":
            expected = {"doctor": "clinician", "admin": "operator", "phone": "operator"}
            if expected.get(path.split("/")[-1]) != role:
                return await deny(403)
        elif method not in {"GET","HEAD","OPTIONS"}:
            operator = path in {"/api/v2/rooms", "/api/v2/admin/test-frame"} or path.endswith(("/config", "/admin-test-frame"))
            if role != ("operator" if operator else "clinician"):
                return await deny(403)
        hospital = headers.get("x-hospital-id")
        if hospital and hospital != HOSPITAL:
            return await deny(403)
        scope["headers"] = [(k,v) for k,v in scope["headers"] if k.lower()!=b"x-hospital-id"] + [(b"x-hospital-id",HOSPITAL.encode())]
        scope.setdefault("state", {})["clinician_email"] = email
        if kind == "http":
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
