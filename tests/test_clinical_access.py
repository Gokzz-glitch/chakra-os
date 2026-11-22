"""Synthetic checks for the backend account gate. No cloud data or credentials are used."""
from unittest.mock import patch

from fastapi import FastAPI, Request, WebSocket
from fastapi.testclient import TestClient
from starlette.websockets import WebSocketDisconnect
import pytest

from clinical_access import ClinicalAccess

app = FastAPI()
app.add_middleware(ClinicalAccess)


@app.api_route("/review", methods=["GET", "POST"])
def review(request: Request):
    return {"actor": request.state.clinician_email, "hospital": request.headers["x-hospital-id"]}


@app.websocket("/ws/v2/example/{role}")
async def socket(ws: WebSocket, role: str):
    await ws.accept()
    await ws.close()


def test_http_grants_and_revocation():
    client = TestClient(app)
    assert client.post("/review").status_code == 401
    signed = {"origin":"http://testserver", "x-goog-iap-jwt-assertion": "synthetic"}
    with patch("clinical_access.identify", return_value=("test@example.invalid","clinician")) as identity:
        assert client.post("/review", headers=signed).json()["actor"] == "test@example.invalid"
        assert client.get("/review", headers={**signed,"x-hospital-id":"OTHER"}).status_code == 403
        identity.return_value = ("test@example.invalid","operator")
        assert client.post("/review", headers=signed).status_code == 403
        identity.return_value = None
        assert client.get("/review", headers=signed).status_code == 403


def test_websocket_role_enforced():
    with patch("clinical_access.identify", return_value=("test@example.invalid","operator")):
        with pytest.raises(WebSocketDisconnect):
            with TestClient(app).websocket_connect("/ws/v2/example/doctor",headers={"origin":"http://testserver","x-goog-iap-jwt-assertion":"synthetic"}):
                pass
