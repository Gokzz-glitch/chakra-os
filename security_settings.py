"""Deployment-scoped tenant and browser security settings."""

import os
from urllib.parse import urlsplit


def setting(name, development_default):
    value = os.getenv(name)
    if value:
        return value
    if (
        os.getenv("ENV", "production" if os.getenv("K_SERVICE") else "development")
        .strip()
        .lower()
        == "production"
    ):
        raise RuntimeError(f"Missing required deployment setting: {name}")
    return development_default


TENANT = setting("CHAKRA_TENANT_ID", "development")
REGION = setting("CHAKRA_REGION", "local")
PRODUCTION = (
    os.getenv("ENV", "production" if os.getenv("K_SERVICE") else "development")
    .strip()
    .lower()
    == "production"
)


PROJECT = setting("GOOGLE_CLOUD_PROJECT", "chakra-development")
MEDIA_BUCKET = setting("GCS_BUCKET", "chakra-development-media")
VISION_URL = setting("VISION_URL", "").rstrip("/")


def browser_origins():
    origins = set()
    for host in setting(
        "ALLOWED_HOSTS", "testserver,localhost:8080,127.0.0.1:8080"
    ).split(","):
        host = host.strip()
        origin = (
            host if "://" in host else ("https://" if PRODUCTION else "http://") + host
        )
        url = urlsplit(origin)
        if (
            not url.hostname
            or url.username
            or url.password
            or url.path
            or url.query
            or url.fragment
            or "*" in origin
        ):
            raise ValueError("ALLOWED_HOSTS must contain exact origins or hosts")
        if PRODUCTION and (
            url.scheme != "https"
            or url.hostname in {"testserver", "localhost", "::1"}
            or url.hostname.startswith("127.")
        ):
            continue
        if url.scheme in {"http", "https"}:
            origins.add(origin)
    return origins


CSP = "default-src 'self'; script-src 'self'; style-src 'self'; object-src 'none'; frame-ancestors 'none'; base-uri 'self'; img-src 'self' data: blob:; media-src 'self' blob: data:; form-action 'self'"
HEADERS = {
    "Content-Security-Policy": CSP,
    "Permissions-Policy": "camera=(self), microphone=(self), geolocation=(), payment=()",
    "Cache-Control": "no-store, max-age=0",
    "X-Content-Type-Options": "nosniff",
    "X-Frame-Options": "DENY",
}
