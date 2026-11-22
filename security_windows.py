"""Window counters shared by Cloud Run instances through conditional object writes."""

import json
import time

from google.api_core.exceptions import NotFound, PreconditionFailed
from google.cloud import storage

from clinical_access import audit_ref
from security_settings import MEDIA_BUCKET, PROJECT


def blocked(kind, actor, seconds, limit, record=True):
    bucket = storage.Client(project=PROJECT).bucket(MEDIA_BUCKET)
    name = f"security-windows/{kind}/{audit_ref(actor)}.json"
    for _ in range(5):
        obj = bucket.blob(name)
        try:
            obj.reload(timeout=3)
            generation = obj.generation
            entries = json.loads(
                obj.download_as_bytes(if_generation_match=generation, timeout=3)
            )
        except NotFound:
            entries, generation = [], 0
        except PreconditionFailed:
            continue
        now = time.time()
        entries = [stamp for stamp in entries if stamp > now - seconds]
        if len(entries) >= limit:
            return True
        if not record:
            return False
        try:
            obj.upload_from_string(
                json.dumps([*entries, now]),
                content_type="application/json",
                if_generation_match=generation,
                timeout=3,
            )
            return False
        except PreconditionFailed:
            continue
    return True  # Contended requests must not bypass a quota.
