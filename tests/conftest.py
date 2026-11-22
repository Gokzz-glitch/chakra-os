"""Local clinical workflow fixtures. No calls to live storage, inference or BigQuery."""

import copy
import os
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import MagicMock, patch

import cv2
import numpy as np
import pytest
from fastapi.testclient import TestClient

os.environ.update(
    ENV="test",
    CHAKRA_TENANT_ID="HOSP-CHENNAI-01",
    CHAKRA_REGION="test",
    ALLOWED_HOSTS="http://testserver",
    VISION_URL="http://vision.invalid",
)
with patch("google.cloud.storage.Client", side_effect=RuntimeError("offline storage")):
    import main

from google.cloud import bigquery, storage
import clinical_access
import clinical_pipeline


class WorkflowClient(TestClient):
    """Drive existing multi-user scenarios as the designated actor for each operation."""

    def request(self, method, url, **kwargs):
        operator = (
            url in {"/v2/admin", "/v2/phone", "/api/v2/admin/test-frame"}
            or (url == "/api/v2/rooms" and method == "POST")
            or (
                url.endswith(("/config", "/admin-test-frame"))
                or (method == "POST" and url.endswith("/patient-consent"))
            )
        )
        headers = {
            "origin": "http://testserver",
            "x-goog-iap-jwt-assertion": "operator" if operator else "clinician",
        }
        headers.update(kwargs.pop("headers", {}) or {})
        return super().request(method, url, headers=headers, **kwargs)

    def websocket_connect(self, url, **kwargs):
        role = "clinician" if url.endswith("/doctor") else "operator"
        return super().websocket_connect(
            url,
            headers={"origin": "http://testserver", "x-goog-iap-jwt-assertion": role},
            **kwargs
        )


@pytest.fixture(scope="session")
def media(tmp_path_factory):
    directory = tmp_path_factory.mktemp("demo-media")
    frame = np.random.default_rng(0).integers(0, 256, (96, 128, 3), dtype=np.uint8)
    for name in (
        "1_1.avi",
        "1_11.avi",
        "1_35.avi",
        "ldpolyp_clip01.mp4",
        "sun_seg_seq01.mp4",
    ):
        codec = "MJPG" if name.endswith(".avi") else "mp4v"
        writer = cv2.VideoWriter(
            str(directory / name), cv2.VideoWriter_fourcc(*codec), 10, (128, 96)
        )
        assert writer.isOpened()
        writer.write(frame)
        writer.release()
        if name.endswith(".mp4"):
            (directory / name.replace(".mp4", "_web_1795211682309814.mp4")).write_bytes(
                (directory / name).read_bytes()
            )
    return str(directory)


@pytest.fixture(autouse=True)
def offline_services(monkeypatch, media):
    import pathology_journal
    from google.api_core.exceptions import PreconditionFailed
    from google.genai.models import Models

    objects = {}

    class Object:
        generation = 1

        def __init__(self, key):
            self.key = key

        def upload_from_string(self, value, *, if_generation_match, **kwargs):
            assert if_generation_match == 0
            if self.key in objects:
                raise PreconditionFailed("exists")
            objects[self.key] = value.encode()

        def download_as_bytes(self, **kwargs):
            return objects[self.key]

    journal = SimpleNamespace(
        blob=Object,
        list_blobs=lambda prefix: [
            Object(key) for key in sorted(objects) if key.startswith(prefix)
        ],
    )
    monkeypatch.setattr(pathology_journal, "bucket", lambda: journal)

    def unavailable(*args, **kwargs):
        raise RuntimeError("offline test service")

    async def health(*args, **kwargs):
        response = MagicMock()
        response.json.return_value = {"status": "ready"}
        return response

    monkeypatch.setattr(Models, "generate_content", unavailable)
    storage_client = MagicMock()
    storage_client.bucket.return_value.name = main.GCS_BUCKET
    storage_client.list_blobs.side_effect = lambda *args, **kwargs: [
        SimpleNamespace(name="demo_videos/" + path.name, size=path.stat().st_size)
        for path in Path(media).iterdir()
        if path.suffix in {".mp4", ".avi"}
    ]
    storage_client.bucket.return_value.blob.return_value.reload.side_effect = (
        unavailable
    )
    monkeypatch.setattr(storage, "Client", lambda **kwargs: storage_client)
    monkeypatch.setattr(main.HTTP_CLIENT, "get", health)
    database = MagicMock()
    database.insert_rows_json.return_value = []
    monkeypatch.setattr(bigquery, "Client", lambda **kwargs: database)
    monkeypatch.setattr(main, "DEMO_CACHE_DIR", media)
    monkeypatch.setattr(main, "PATIENT_REGISTRY", copy.deepcopy(main.PATIENT_REGISTRY))
    monkeypatch.setattr(main, "RUN_LOGS", copy.deepcopy(main.RUN_LOGS))
    for name in ("ROOMS", "SOCKETS", "paired_actors", "SESSIONS_V1"):
        monkeypatch.setattr(main, name, {})
    main.request_windows.clear()
    main.pairing_failures.clear()
    monkeypatch.setattr(
        clinical_access,
        "identify",
        lambda token: (
            (token + "@example.invalid", token)
            if token in {"operator", "clinician"}
            else None
        ),
    )
