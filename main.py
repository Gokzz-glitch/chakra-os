import secrets, logging, binascii
import pathology_journal
import security_windows
from security_settings import HEADERS, TENANT, REGION, PROJECT, MEDIA_BUCKET as GCS_BUCKET, VISION_URL, browser_origins
import asyncio, base64, datetime, io, json, os, re, tempfile, time, uuid
from typing import Literal
from collections import OrderedDict, deque
from ipaddress import ip_address
from typing import Any, Dict, List, Optional
import httpx
from fastapi import FastAPI, File, Form, Header, HTTPException, Request, Response, UploadFile, WebSocket, WebSocketDisconnect
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import HTMLResponse, RedirectResponse, StreamingResponse, FileResponse, JSONResponse
from google.cloud import storage
from pydantic import BaseModel, Field, StrictBool
from clinical_pipeline import (
    build_clinical_report,
    commit_and_query_bq,
    get_bq_analytics,
    parse_voice_note,
    scrub_phi,
    synthesize_discharge_audio,
    upload_evidence_frame,
)

ENV = os.getenv("ENV", "production" if os.getenv("K_SERVICE") else "development").lower()
is_prod = (ENV == "production")

app = FastAPI(
    title="CHAKRA Clinical OS V2",
    docs_url=None if is_prod else "/docs",
    redoc_url=None if is_prod else "/redoc",
    openapi_url=None if is_prod else "/openapi.json",
)

ALLOWED_ORIGINS = sorted(browser_origins())

app.add_middleware(
    CORSMiddleware,
    allow_origins=ALLOWED_ORIGINS,
    allow_credentials=True,
    allow_methods=["GET", "POST", "PATCH", "PUT", "DELETE", "OPTIONS"],
    allow_headers=["*"],
)

@app.exception_handler(Exception)
async def global_exception_handler(request: Request, exc: Exception):
    if isinstance(exc, HTTPException):
        return JSONResponse(status_code=exc.status_code, content={"detail": exc.detail})
    req_id = uuid.uuid4().hex[:8]
    return JSONResponse(
        status_code=500, headers=HEADERS,
        content={
            "detail": "An internal clinical OS error occurred. Please contact systems administrator.",
            "request_id": req_id,
            "status": "error"
        }
    )

pairing_failures = OrderedDict()
paired_actors = {}


def pairing_expired(actor, room):
    return (time.monotonic() >= room["pairing_expires_at"]
            and not (room.get("started_ts") is not None and actor in paired_actors.get(room["code"], set())))


request_windows = OrderedDict()


async def window_blocked(kind, actor, seconds, limit, record=True):
    if is_prod:
        try:
            return await asyncio.to_thread(security_windows.blocked, kind, actor, seconds, limit, record)
        except Exception:
            logging.getLogger("clinical").warning('{"event":"security_counter_unavailable"}')
            return True
    windows = pairing_failures if kind == "pairing" else request_windows
    now = time.monotonic()
    entries = windows.setdefault(actor, deque())
    windows.move_to_end(actor)
    if len(windows) > 8192:
        windows.popitem(last=False)
    while entries and entries[0] <= now - seconds:
        entries.popleft()
    if len(entries) >= limit:
        return True
    if record:
        entries.append(now)
    return False


async def pairing_locked(actor, code):
    invalid = code not in ROOMS or pairing_expired(actor, ROOMS[code])
    return await window_blocked("pairing", actor, 900, 5, invalid)


metered_action = re.compile(r"^/api/v2/(?:rooms/[^/]+/(?:voice-note|end-report|tts|admin-test-frame)|voice-parse|report|tts|admin/test-frame)/?$")

def rate_identity(request):
    email = getattr(request.state, "clinician_email", None)
    if email:
        return email
    peer = request.client.host if request.client else "unknown"
    trusted = {ip.strip() for ip in os.getenv("TRUSTED_PROXY_IPS", "").split(",")}
    if peer in trusted:
        try:
            return str(ip_address(request.headers.get("x-forwarded-for", "").split(",")[-1].strip()))
        except ValueError:
            pass
    return peer


@app.middleware("http")
async def security_and_rate_limit_middleware(request: Request, call_next):
    env_curr = os.getenv("ENV", "production" if os.getenv("K_SERVICE") else "development").lower()
    if env_curr == "production" and request.url.path in ("/docs", "/redoc", "/openapi.json"):
        return Response(content=json.dumps({"detail": "Not Found"}), status_code=404, media_type="application/json")

    room_match = re.fullmatch(r"/api/v2/rooms/([^/]+)(?:/.*)?", request.url.path.rstrip("/"))
    if room_match and await pairing_locked(request.state.clinician_email, room_match[1]):
        return JSONResponse({"detail": "Too many unsuccessful pairing attempts"}, status_code=429)
    if room_match and room_match[1] in ROOMS and pairing_expired(request.state.clinician_email, ROOMS[room_match[1]]):
        return JSONResponse({"detail":"Pairing expired"}, status_code=404)
    if room_match and room_match[1] in ROOMS:
        paired_actors.setdefault(room_match[1], set()).add(request.state.clinician_email)
    limited = False
    path = request.url.path.rstrip("/")
    if (metered_action.fullmatch(path) or path == "/api/analyze" or path == "/api/v2/rooms"
            or path.startswith("/api/v2/patients/") or path.endswith("/signoff")):
        limited = await window_blocked("requests", rate_identity(request), 60, 30)

    if limited:
        response = Response(
            content=json.dumps({"detail": "Rate limit exceeded. Maximum 30 requests per minute on AI/GPU endpoints.", "retry_after": 60}),
            status_code=429,
            media_type="application/json",
            headers={"Retry-After": "60"}
        )
    else:
        response = await call_next(request)

    response.headers["X-Content-Type-Options"] = "nosniff"
    response.headers["X-Frame-Options"] = "DENY"
    response.headers["Referrer-Policy"] = "strict-origin-when-cross-origin"
    response.headers["Strict-Transport-Security"] = "max-age=63072000; includeSubDomains"
    return response

@app.get("/static/{asset}")
def page_asset(asset: str):
    if not re.fullmatch(r"[a-zA-Z0-9_.-]+\.(?:js|css)", asset):
        raise HTTPException(404, "Unknown asset")
    filename = os.path.join("static", asset)
    if not os.path.isfile(filename):
        raise HTTPException(404, "Unknown asset")
    return FileResponse(filename)


@app.get("/v2/doctor/history", response_class=HTMLResponse)
def doctor_history_map():
    return FileResponse("static/patient-history.html", media_type="text/html")

@app.get("/v2/assets/operation-feedback.js")
def operation_feedback_script():
    return FileResponse("static/operation-feedback.js", media_type="text/javascript")

@app.get("/v2/assets/cohort-index.json")
def cohort_index():
    return FileResponse("static/cohort-index.json", media_type="application/json")

@app.get("/v2/assets/cohort-map.js")
def cohort_script():
    return FileResponse("static/cohort-map.js", media_type="text/javascript")

@app.get("/v2/assets/patient-history.js")
def patient_history_script():
    return FileResponse("static/patient-history.js", media_type="text/javascript")

DEMO_CACHE_DIR = os.path.join(tempfile.gettempdir(), "chakra_demo_videos")

SESSIONS_V1: Dict[str, Any] = {}
ROOMS: Dict[str, Dict[str, Any]] = {}
SOCKETS: Dict[str, Dict[str, List[WebSocket]]] = {}
HTTP_CLIENT = httpx.AsyncClient(timeout=45.0)

MODEL_CATALOG = [
    {"id": "yolovit_yolo", "name": "YOLOViT-YOLO (weights.pt)", "type": "Real-Time CADe (L4)", "status": "verified", "default": True},
    {"id": "pvt_pranet_v1", "name": "PVT-PraNet-V1 (PVTv2-B2)", "type": "Segmentation", "status": "gcs_staged", "default": False},
    {"id": "chakranet", "name": "AdaBN-ChakraNet (ResNet-101)", "type": "Segmentation", "status": "gcs_staged", "default": False},
    {"id": "sepnet", "name": "SEPNet (PVTv2-B2)", "type": "Segmentation", "status": "gcs_staged", "default": False},
    {"id": "rf_detr_s", "name": "RF-DETR-Small (Apache 2.0 Roadmap)", "type": "Commercial CADe Target", "status": "roadmap", "default": False},
]

def _read_html(name: str) -> str:
    return open(name, encoding="utf-8").read()

async def _broadcast(code: str, roles: List[str], message: Dict[str, Any]):
    room_socks = SOCKETS.get(code, {})
    for role in roles:
        dead = []
        for ws in list(room_socks.get(role, [])):
            try:
                await ws.send_json(message)
            except Exception:
                dead.append(ws)
        for ws in dead:
            room_socks[role].remove(ws)

# ---- Helper Functions: Video Security, Zero-Disk Direct Streaming & Ephemeral Frame Extraction ----
MAX_IMAGE_BYTES = 5 * 1024 * 1024


def validate_image(raw):
    if len(raw) > MAX_IMAGE_BYTES:
        raise HTTPException(413, "Frame exceeds 5 MiB")
    if not raw.startswith((b"\xff\xd8\xff", b"\x89PNG\r\n\x1a\n")):
        raise HTTPException(415, "Expected JPEG or PNG")
    return raw


def safe_filename(filename):
    basename = (filename or "frame").replace("\\", "/").rsplit("/", 1)[-1]
    return re.sub(r"[^A-Za-z0-9._-]", "_", basename)[:128].strip(".") or "frame"


def decode_frame(value):
    if not isinstance(value, str) or len(value) > 4 * ((MAX_IMAGE_BYTES + 2) // 3) + 32:
        raise HTTPException(413, "Invalid frame length")
    try:
        return validate_image(base64.b64decode(value.split(",", 1)[-1], validate=True))
    except (ValueError, binascii.Error):
        raise HTTPException(400, "Invalid frame encoding")


def _sanitize_video_name(name: str) -> str:
    if not name or ".." in name or "/" in name or "\\" in name or "\x00" in name:
        raise HTTPException(status_code=400, detail="Invalid video name: path traversal blocked")
    if not re.match(r"^[a-zA-Z0-9_\-\.]+\.(mp4|avi)$", name, re.IGNORECASE):
        raise HTTPException(status_code=400, detail="Invalid video name: unsupported extension or illegal characters")
    return name

def _stream_video_direct(clean_name: str, range_header: Optional[str], media_type: str) -> Response:
    """Serve real bytes from a pinned object generation or an available local file."""
    from google.api_core.exceptions import NotFound
    local_path = os.path.join(DEMO_CACHE_DIR, clean_name)
    try:
        client = storage.Client(project=PROJECT)
        blob = client.bucket(GCS_BUCKET).blob(f"demo_videos/{clean_name}")
        blob.reload()
        size = blob.size
    except Exception as exc:
        blob = None
        if not os.path.isfile(local_path):
            code = 404 if isinstance(exc, NotFound) else 503
            raise HTTPException(code, "Recording missing" if code == 404 else "Media storage unavailable") from exc
        size = os.path.getsize(local_path)
    if not size:
        raise HTTPException(422, "Recording is empty")

    start, end = 0, size - 1
    headers = {"Accept-Ranges": "bytes", "Cache-Control": "public, max-age=3600"}
    if range_header:
        invalid = HTTPException(416, "Range not satisfiable", headers={"Content-Range": f"bytes */{size}"})
        match = re.fullmatch(r"bytes=(\d*)-(\d*)", range_header.strip())
        if not match or not any(match.groups()):
            raise invalid
        first, last = match.groups()
        if first:
            start = int(first)
            if last:
                end = min(int(last), end)
        else:
            start = max(0, size - int(last))
        if start > end:
            raise invalid
        headers["Content-Range"] = f"bytes {start}-{end}/{size}"

    length = end - start + 1
    headers["Content-Length"] = str(length)
    def chunks():
        reader = blob.open("rb", chunk_size=1024*1024) if blob is not None else open(local_path, "rb")
        with reader:
            reader.seek(start)
            remaining = length
            while remaining:
                part = reader.read(min(remaining, 256*1024))
                if not part:
                    raise IOError("Recording ended early")
                yield part
                remaining -= len(part)
    return StreamingResponse(chunks(), status_code=206 if range_header else 200, media_type=media_type, headers=headers)

def _extract_video_frame(clean_name: str, frame_idx: int = 0) -> bytes:
    """Extracts frame via OpenCV, caches only the lightweight 32KB JPEG, and purges heavy video tempfiles."""
    os.makedirs(DEMO_CACHE_DIR, exist_ok=True)
    frame_cache_path = os.path.join(DEMO_CACHE_DIR, f"{clean_name}_f{frame_idx}.jpg")
    if os.path.exists(frame_cache_path) and os.path.getsize(frame_cache_path) > 0:
        with open(frame_cache_path, "rb") as f:
            return f.read()

    vid_tmp_path = os.path.join(DEMO_CACHE_DIR, clean_name)
    downloaded_tmp = False
    if not os.path.exists(vid_tmp_path) or os.path.getsize(vid_tmp_path) == 0:
        try:
            st = storage.Client(project=PROJECT)
            blob = st.bucket(GCS_BUCKET).blob(f"demo_videos/{clean_name}")
            blob.download_to_filename(vid_tmp_path)
            downloaded_tmp = True
        except Exception as e:
            if not os.path.exists(vid_tmp_path):
                raise HTTPException(status_code=502, detail=f"Storage download failed: {str(e)}")

    try:
        import cv2
        cap = cv2.VideoCapture(vid_tmp_path)
        try:
            total_frames = int(cap.get(cv2.CAP_PROP_FRAME_COUNT))
            if total_frames > 0 and frame_idx > 0:
                cap.set(cv2.CAP_PROP_POS_FRAMES, min(frame_idx, total_frames - 1))
            ret, frame = cap.read()
            if not ret or frame is None:
                raise HTTPException(status_code=500, detail="Failed to read video frame via OpenCV")
            ok, buf = cv2.imencode(".jpg", frame, [int(cv2.IMWRITE_JPEG_QUALITY), 85])
            if not ok:
                raise HTTPException(status_code=500, detail="Failed to encode frame as JPEG")
            jpeg_bytes = buf.tobytes()
            with open(frame_cache_path, "wb") as f:
                f.write(jpeg_bytes)
            return jpeg_bytes
        finally:
            cap.release()
    finally:
        # Free Cloud Run tmpfs RAM immediately if temporary video file was downloaded
        if downloaded_tmp and os.path.exists(vid_tmp_path):
            try:
                os.remove(vid_tmp_path)
            except OSError:
                pass

@app.get("/logo.png")
def get_logo():
    for p in ("static/logo.png", "logo.png", "submission_assets/logo.png"):
        if os.path.exists(p):
            return FileResponse(p, media_type="image/png")
    raise HTTPException(404, "Logo not found")

# ---- Routes: Root & Versioned Pages ----
@app.get("/")
def root():
    return RedirectResponse("/v2/admin")

@app.get("/v1", response_class=HTMLResponse)
def v1_home():
    return _read_html("index_v1.html" if os.path.exists("index_v1.html") else "admin.html")

@app.get("/v2/admin", response_class=HTMLResponse)
def v2_admin():
    return _read_html("admin.html")

@app.get("/v2/phone", response_class=HTMLResponse)
def v2_phone():
    return _read_html("phone.html")

@app.get("/v2/doctor", response_class=HTMLResponse)
def v2_doctor():
    return _read_html("doctor.html")

# ---- Shared Health & V1 Endpoints ----
@app.get("/api/warmup")
async def warmup():
    if not VISION_URL:
        return {"status": "offline", "gpu": "CPU Fallback"}
    try:
        r = await HTTP_CLIENT.get(f"{VISION_URL}/warmup", timeout=5.0)
        return r.json()
    except Exception as e:
        return {"status": "warming", "detail": str(e)}

@app.post("/api/analyze")
async def v1_analyze(
    request: Request, file: UploadFile = File(...),
    bbps_r: int = Form(..., ge=0, le=3), bbps_t: int = Form(..., ge=0, le=3), bbps_l: int = Form(..., ge=0, le=3),
    withdrawal_sec: int = Form(..., ge=0)
):
    img_bytes = validate_image(await file.read(MAX_IMAGE_BYTES + 1))
    vision = await detect_image(img_bytes, safe_filename(file.filename))
    proc_id = f"PROC-{datetime.date.today().strftime('%Y%m%d')}-{uuid.uuid4().hex[:6].upper()}"
    payload = {
        "procedure_id": proc_id, "endoscopist_id": request.state.clinician_email,
        "patient_anonymized_id": f"ABHA-HASH-{uuid.uuid4().hex[:6].upper()}",
        "withdrawal_time_seconds": withdrawal_sec,
        "bbps_scores": {"right": bbps_r, "transverse": bbps_t, "left": bbps_l},
        "detections": vision.get("detections", []), "latency_ms": vision.get("latency_ms", 0.0),
    }
    report = build_clinical_report(payload, hitl_approved=False)
    SESSIONS_V1[proc_id] = payload
    return {"vision": vision, "report": report}

class SignoffReq(BaseModel):
    hitl_attested: StrictBool

@app.post("/api/signoff/{proc_id}")
def v1_signoff(proc_id: str, request: Request, attestation: "SignoffReq"):
    if not attestation.hitl_attested:
        raise HTTPException(400, "Clinician attestation required")
    if proc_id not in SESSIONS_V1:
        raise HTTPException(404, "Procedure ID not found")
    payload = dict(SESSIONS_V1[proc_id], signed_by=request.state.clinician_email)
    final_report = build_clinical_report(payload, hitl_approved=True)
    return {"report": final_report, "bigquery": commit_and_query_bq(payload, final_report, hitl_approved=True)}

# ---- V2 Session, Pairing & Clinical Workflow APIs ----
class RoomConfigUpdate(BaseModel):
    model: str = "yolovit_yolo"
    conf: float = 0.45
    worker: str = "cloud_run_l4"
    endoscopist_id: str = "DR-GOKUL-R"
    patient_label: str = "DEMO-PATIENT-01"
    bbps_right: Optional[int] = Field(None, ge=0, le=3)
    bbps_transverse: Optional[int] = Field(None, ge=0, le=3)
    bbps_left: Optional[int] = Field(None, ge=0, le=3)

class VoiceNoteReq(BaseModel):
    transcript: str = Field(..., max_length=2000)

class FindingReviewReq(BaseModel):
    finding_id: str
    decision: Literal["accepted", "dismissed"]

class TtsReq(BaseModel):
    text: str
    voice_name: str = "Kore"

class PatientConsentReq(BaseModel):
    aware_of_procedure: bool = True
    consent_data_sharing: bool = True
    patient_signature: Optional[str] = "PATIENT_VERIFIED"
    language: str = "en"

# ---- Standalone Public AI/GPU Endpoints ----
@app.post("/api/v2/voice-parse")
def standalone_voice_parse(req: VoiceNoteReq):
    if len(req.transcript) > 2000:
        raise HTTPException(400, "Transcript exceeds maximum allowed length of 2,000 characters")
    return {"ok": True, "parsed": parse_voice_note(req.transcript)}

@app.post("/api/v2/report")
def standalone_report(payload: Dict[str, Any]):
    report = build_clinical_report(payload, hitl_approved=False)
    return {"ok": True, "report": report}

@app.post("/api/v2/tts")
def standalone_tts(req: TtsReq):
    result = synthesize_discharge_audio(req.text, req.voice_name)
    if not result.get("audio_b64"):
        raise HTTPException(503, "Speech synthesis unavailable")
    return Response(base64.b64decode(result["audio_b64"], validate=True), media_type="audio/wav")

@app.post("/api/v2/admin/test-frame")
async def standalone_admin_test_frame(file: UploadFile = File(...)):
    raw = validate_image(await file.read(MAX_IMAGE_BYTES + 1))
    return await detect_image(raw, safe_filename(file.filename))


async def detect_image(raw, filename, confidence=None, timeout=10):
    try:
        if not VISION_URL:
            raise ValueError("Inference service is unconfigured")
        response = await HTTP_CLIENT.post(
            f"{VISION_URL}/detect", params={"conf": confidence} if confidence is not None else {},
            files={"file": (filename, raw, "image/png" if raw.startswith(b"\x89PNG") else "image/jpeg")},
            timeout=timeout)
        response.raise_for_status()
        result = response.json()
        if not isinstance(result.get("detections"), list) or type(result.get("count")) is not int:
            raise ValueError("Incomplete inference result")
        if result["count"] != len(result["detections"]):
            raise ValueError("Inconsistent detection count")
        return result
    except (httpx.HTTPError, OSError, ValueError, AttributeError) as exc:
        raise HTTPException(503, "Inference is unavailable") from exc


@app.get("/api/v2/session")
def session_context(request: Request):
    return {"role": request.state.role, "tenant": TENANT, "region": REGION, "project": PROJECT,
            "vision_region": os.getenv("VISION_REGION"), "media_bucket": GCS_BUCKET}


@app.get("/api/v2/catalog")
def get_catalog():
    return {"models": MODEL_CATALOG, "vision_url": VISION_URL}

@app.get("/api/v2/analytics")
def analytics():
    try:
        return get_bq_analytics()
    except Exception as e:
        return {"table": "chakra_clinical_dw.procedures", "metrics": [], "error": str(e)}

# ---- Demo Videos Endpoints (Range/206 Direct GCS + OpenCV Fallback) ----
@app.get("/api/v2/demo-videos")
def list_demo_videos():
    videos = []
    try:
        st = storage.Client(project=PROJECT)
        bucket = st.bucket(GCS_BUCKET)
        blobs = list(st.list_blobs(bucket, prefix="demo_videos/"))
        for b in blobs:
            fname = os.path.basename(b.name)
            if not fname:
                continue
            ext = fname.split(".")[-1].lower()
            ctype = "video/mp4" if ext == "mp4" else ("video/x-msvideo" if ext == "avi" else "application/octet-stream")
            item = {
                "name": fname,
                "filename": fname,
                "size_bytes": b.size or 0,
                "content_type": ctype,
                "format": ext,
                "stream_url": f"/api/v2/demo-videos/{fname}",
            }
            if ext == "avi":
                item["frame_extract_url"] = f"/api/v2/demo-videos/{fname}/frame"
                item["fallback_note"] = "OpenCV frame extraction fallback enabled for non-native AVI browsers"
            videos.append(item)
    except Exception:
        videos = [
            {"name": "ldpolyp_clip01.mp4", "filename": "ldpolyp_clip01.mp4", "size_bytes": 28733, "content_type": "video/mp4", "format": "mp4", "stream_url": "/api/v2/demo-videos/ldpolyp_clip01.mp4"},
            {"name": "sun_seg_seq01.mp4", "filename": "sun_seg_seq01.mp4", "size_bytes": 27304, "content_type": "video/mp4", "format": "mp4", "stream_url": "/api/v2/demo-videos/sun_seg_seq01.mp4"},
            {"name": "1_35.avi", "filename": "1_35.avi", "size_bytes": 34839050, "content_type": "video/x-msvideo", "format": "avi", "stream_url": "/api/v2/demo-videos/1_35.avi", "frame_extract_url": "/api/v2/demo-videos/1_35.avi/frame", "fallback_note": "OpenCV frame extraction fallback enabled for non-native AVI browsers"},
        ]
    return {"bucket": GCS_BUCKET, "videos": videos}

@app.get("/api/v2/demo-videos/{name}")
def get_demo_video(
    name: str,
    request: Request,
    range: Optional[str] = Header(None),
    extract: Optional[bool] = None,
    frame: Optional[int] = None,
):
    clean_name = _sanitize_video_name(name)
    accept_hdr = request.headers.get("accept", "").lower()
    is_avi = clean_name.lower().endswith(".avi")

    # If client requests frame extract directly or sends image-only Accept header for AVI
    if extract or frame is not None or (is_avi and "image/" in accept_hdr and "video/" not in accept_hdr):
        jpeg_bytes = _extract_video_frame(clean_name, frame_idx=frame or 0)
        return Response(
            content=jpeg_bytes,
            media_type="image/jpeg",
            headers={"Content-Type": "image/jpeg", "X-Frame-Fallback": "OpenCV-AVI-Extract"}
        )

    media_type = "video/x-msvideo" if is_avi else "video/mp4"
    # Keep original files for frame extraction; serve fast-start H.264 to video players.
    playback_names = {
        "ldpolyp_clip01.mp4": "ldpolyp_clip01_web_1795211682309814.mp4",
        "sun_seg_seq01.mp4": "sun_seg_seq01_web_1795211682309814.mp4",
    }
    resp = _stream_video_direct(playback_names.get(clean_name, clean_name), range, media_type)
    if is_avi:
        resp.headers["X-Frame-Extract-Fallback"] = f"/api/v2/demo-videos/{clean_name}/frame"
    return resp

@app.get("/api/v2/demo-videos/{name}/frame")
def get_demo_video_frame(name: str, idx: int = 0):
    clean_name = _sanitize_video_name(name)
    jpeg_bytes = _extract_video_frame(clean_name, frame_idx=idx)
    return Response(
        content=jpeg_bytes,
        media_type="image/jpeg",
        headers={"Content-Type": "image/jpeg", "X-Frame-Index": str(idx)}
    )

@app.post("/api/v2/rooms")
async def create_room():
    for old_code, old_room in list(ROOMS.items()):
        if old_room["pairing_expires_at"] <= time.monotonic() and not old_room.get("started_ts") and not any(SOCKETS.get(old_code, {}).values()):
            paired_actors.pop(old_code, None)
            ROOMS.pop(old_code)
            SOCKETS.pop(old_code, None)
    if len(ROOMS) >= 4096:
        raise HTTPException(503, "Room capacity reached")
    code = str(100000 + secrets.randbelow(900000))
    while code in ROOMS:
        code = str(100000 + secrets.randbelow(900000))
    proc_id = f"PROC-{datetime.date.today().strftime('%Y%m%d')}-{code}"
    ROOMS[code] = {
        "pairing_expires_at": time.monotonic() + 900,
        "code": code,
        "procedure_id": proc_id,
        "patient_anonymized_id": f"ABHA-HASH-{code}",
        "patient_label": "DEMO-PATIENT-01",
        "endoscopist_id": "DR-GOKUL-R",
        "patient_consent": {
            "verified": False,
            "aware_of_procedure": False,
            "consent_data_sharing": False,
            "consent_id": None,
            "verified_at": None,
            "hospital_id": TENANT,
        },
        "model": "yolovit_yolo",
        "conf": 0.45,
        "worker": "cloud_run_l4",
        "phone_connected": False,
        "doctor_started": False,
        "started_ts": None,
        "withdrawal_sec": None,
        "bbps_scores": dict.fromkeys(("right", "transverse", "left")),
        "frames_processed": 0,
        "latencies": [],
        "in_flight": False,
        "findings": [],
        "voice_notes": [],
        "suspected_location": "Cecum / Ascending",
        "max_mm": None,
        "last_report": None,
    }
    SOCKETS[code] = {"admin": [], "phone": [], "doctor": []}
    return ROOMS[code]

@app.get("/api/v2/rooms/{code}")
def get_room(code: str, request: Request):
    if code not in ROOMS:
        raise HTTPException(404, "Pairing code not found")
    r = ROOMS[code]
    if request.state.role == "operator":
        return {key: r[key] for key in (
            "code", "procedure_id", "model", "conf", "worker", "endoscopist_id", "patient_label",
            "phone_connected", "doctor_started", "frames_processed")}
    return {k: v for k, v in r.items() if k != "in_flight"}

@app.post("/api/v2/rooms/{code}/patient-consent")
async def verify_patient_consent(code: str, req: PatientConsentReq):
    if code not in ROOMS:
        raise HTTPException(404, "Pairing code not found")
    if not req.aware_of_procedure or not req.consent_data_sharing:
        raise HTTPException(
            400,
            detail="Patient must verify awareness of the procedure and consent to data sharing to proceed."
        )
    r = ROOMS[code]
    consent_id = f"DPDP-{uuid.uuid4().hex[:8].upper()}"
    now_iso = datetime.datetime.now(datetime.timezone.utc).isoformat()
    consent_record = {
        "verified": True,
        "aware_of_procedure": True,
        "consent_data_sharing": True,
        "consent_id": consent_id,
        "verified_at": now_iso,
        "patient_signature": req.patient_signature or "PATIENT_VERIFIED",
        "patient_anonymized_id": r["patient_anonymized_id"],
        "hospital_id": TENANT,
        "language": req.language,
        "standard": "India DPDP Act 2023 & ABDM FHIR R4 Consent",
    }
    r["patient_consent"] = consent_record
    await _broadcast(code, ["admin", "doctor", "phone"], {
        "type": "patient_consent_updated",
        "patient_consent": consent_record
    })
    return {"ok": True, "patient_consent": consent_record}

@app.get("/api/v2/rooms/{code}/patient-consent")
def get_patient_consent(code: str):
    if code not in ROOMS:
        raise HTTPException(404, "Pairing code not found")
    return {"ok": True, "patient_consent": ROOMS[code].get("patient_consent", {"verified": False})}

@app.patch("/api/v2/rooms/{code}/config")
async def update_config(code: str, cfg: RoomConfigUpdate, request: Request):
    if code not in ROOMS:
        raise HTTPException(404, "Pairing code not found")
    r = ROOMS[code]
    r["last_payload"] = None
    r["model"] = cfg.model
    r["conf"] = max(0.1, min(0.95, cfg.conf))
    r["worker"] = cfg.worker
    r["endoscopist_id"] = cfg.endoscopist_id
    r["patient_label"] = cfg.patient_label
    await _broadcast(code, ["admin", "doctor", "phone"], {"type": "config_updated", "config": cfg.model_dump()})
    return {"ok": True, "room": get_room(code, request)}

class ClinicalMeasurements(BaseModel):
    right: int = Field(ge=0, le=3)
    transverse: int = Field(ge=0, le=3)
    left: int = Field(ge=0, le=3)
    max_mm: float = Field(ge=0, allow_inf_nan=False)


@app.post("/api/v2/rooms/{code}/measurements")
async def confirm_measurements(code: str, entry: ClinicalMeasurements):
    if code not in ROOMS:
        raise HTTPException(404, "Room unavailable")
    room = ROOMS[code]
    room["bbps_scores"] = entry.model_dump(exclude={"max_mm"})
    room["max_mm"] = entry.max_mm
    room["measurements_confirmed"] = True
    room["last_payload"] = None
    return {"ok": True}


@app.post("/api/v2/rooms/{code}/doctor-start")
async def doctor_start(code: str):
    if code not in ROOMS:
        raise HTTPException(404, "Pairing code not found")
    r = ROOMS[code]
    if r["doctor_started"]:
        return {"ok": True, "doctor_started": True}
    r["last_payload"] = None
    r["doctor_started"] = True
    r["withdrawal_sec"] = None
    r["started_ts"] = time.time()
    r["in_flight"] = False
    await _broadcast(code, ["admin", "doctor", "phone"], {"type": "procedure_started", "started_ts": r["started_ts"]})
    return {"ok": True, "doctor_started": True}

@app.post("/api/v2/rooms/{code}/finding-review")
async def review_finding(code: str, req: FindingReviewReq):
    if code not in ROOMS:
        raise HTTPException(404, "Pairing code not found")
    r = ROOMS[code]
    for f in r["findings"]:
        if f["id"] == req.finding_id:
            r["last_payload"] = None
            f["status"] = req.decision
            break
    await _broadcast(code, ["doctor"], {"type": "findings_updated", "findings": r["findings"]})
    return {"ok": True, "findings": r["findings"]}

@app.post("/api/v2/rooms/{code}/voice-note")
async def add_voice_note(code: str, req: VoiceNoteReq):
    if code not in ROOMS:
        raise HTTPException(404, "Pairing code not found")
    if len(req.transcript) > 2000:
        raise HTTPException(400, "Transcript exceeds maximum allowed length of 2,000 characters")
    r = ROOMS[code]
    parsed = parse_voice_note(req.transcript)
    r["measurements_confirmed"] = False
    r["last_payload"] = None
    if parsed.get("bbps_right") is not None: r["bbps_scores"]["right"] = int(parsed["bbps_right"])
    if parsed.get("bbps_transverse") is not None: r["bbps_scores"]["transverse"] = int(parsed["bbps_transverse"])
    if parsed.get("bbps_left") is not None: r["bbps_scores"]["left"] = int(parsed["bbps_left"])
    if parsed.get("suspected_location"): r["suspected_location"] = parsed["suspected_location"]
    if parsed.get("suspected_size_mm"): r["max_mm"] = float(parsed["suspected_size_mm"])
    r["voice_notes"].append(parsed["clinical_note"])
    await _broadcast(code, ["doctor"], {
        "type": "voice_parsed", "parsed": parsed, "bbps_scores": r["bbps_scores"],
        "suspected_location": r["suspected_location"], "voice_notes": r["voice_notes"]
    })
    return {"ok": True, "parsed": parsed, "bbps_scores": r["bbps_scores"]}

@app.post("/api/v2/rooms/{code}/admin-test-frame")
async def admin_test_frame(code: str, file: UploadFile = File(...)):
    if code not in ROOMS:
        raise HTTPException(404, "Pairing code not found")
    r = ROOMS[code]
    raw = validate_image(await file.read(MAX_IMAGE_BYTES + 1))
    if r["worker"] != "cloud_run_l4":
        raise HTTPException(503, "Selected worker does not support inference")
    res = await detect_image(raw, safe_filename(file.filename), r["conf"])
    _record_test_frame_run(r, safe_filename(file.filename) or "admin_test_frame.jpg", res)
    return res

@app.post("/api/v2/rooms/{code}/end-report")
async def end_and_generate_report(code: str):
    if code not in ROOMS:
        raise HTTPException(404, "Pairing code not found")
    r = ROOMS[code]
    r["doctor_started"] = False
    if r["withdrawal_sec"] is None and r["started_ts"] is not None:
        r["withdrawal_sec"] = max(0, int(time.time() - r["started_ts"]))
    approved = [f for f in r["findings"] if f.get("status") == "accepted"]
    gcs_uri = None
    if approved and approved[0].get("thumb_b64"):
        gcs_uri = upload_evidence_frame(r["procedure_id"], approved[0]["thumb_b64"])
    mean_lat = round(sum(r["latencies"]) / len(r["latencies"]), 1) if r["latencies"] else 28.0
    payload = {
        "procedure_id": r["procedure_id"],
        "endoscopist_id": r["endoscopist_id"],
        "patient_anonymized_id": r["patient_anonymized_id"],
        "patient_consent": r.get("patient_consent", {}),
        "withdrawal_time_seconds": r["withdrawal_sec"],
        "bbps_scores": r["bbps_scores"],
        "approved_findings": [{k: v for k, v in f.items() if k != "thumb_b64"} for f in approved],
        "voice_notes": r["voice_notes"],
        "max_mm": r.get("max_mm"),
        "latency_ms": mean_lat,
        "edge_model": f"{r['model']} ({r['worker']})",
        "evidence_gcs_uri": gcs_uri,
    }
    if any(v is None for v in r["bbps_scores"].values()):
        raise HTTPException(409, "Enter all three bowel preparation scores")
    report = build_clinical_report(payload, hitl_approved=False)
    r["last_payload"] = payload
    r["last_report"] = report
    _record_procedure_run(r, approved, mean_lat, gcs_uri)
    await _broadcast(code, ["admin", "doctor", "phone"], {"type": "procedure_ended", "procedure_id": r["procedure_id"]})
    return {"report": report, "findings": r["findings"], "withdrawal_sec": r["withdrawal_sec"]}

@app.post("/api/v2/rooms/{code}/tts")
def room_tts(code: str, req: TtsReq):
    if code not in ROOMS:
        raise HTTPException(404, "Pairing code not found")
    return synthesize_discharge_audio(req.text, req.voice_name)

@app.post("/api/v2/rooms/{code}/signoff")
async def room_signoff(code: str, req: SignoffReq, request: Request):
    if code not in ROOMS:
        raise HTTPException(404, "Pairing code not found")
    if not req.hitl_attested:
        raise HTTPException(400, "Mandatory clinician HITL attestation required before BigQuery commit")
    r = ROOMS[code]
    if not r.get("measurements_confirmed") or r.get("withdrawal_sec") is None:
        raise HTTPException(409, "Confirm clinical measurements and record withdrawal time before sign-off")
    if not r.get("last_payload"):
        raise HTTPException(400, "Generate report before sign-off")
    if any(f.get("status") not in {"accepted", "dismissed"} for f in r["findings"]):
        raise HTTPException(409, "Review pending findings before sign-off")
    r["last_payload"]["signed_by"] = request.state.clinician_email
    final_report = build_clinical_report(r["last_payload"], hitl_approved=True)
    bq_res = commit_and_query_bq(r["last_payload"], final_report, hitl_approved=True)
    await _broadcast(code, ["doctor"], {"type": "signed_off", "bigquery": bq_res})
    return {"report": final_report, "bigquery": bq_res}

# ---- Real-Time WebSocket Room (Depth-1 Non-Blocking L4 Relay) ----
async def _process_phone_frame(code: str, msg: Dict[str, Any]):
    r = ROOMS.get(code)
    if not r or not r.get("doctor_started"):
        if r:
            r["in_flight"] = False
        return
    try:
        raw_b64 = msg.get("image_b64", "")
        raw = decode_frame(raw_b64)
        if r["worker"] != "cloud_run_l4" or not VISION_URL:
            raise RuntimeError("Inference backend unavailable")
        vision = await detect_image(raw, "frame", r["conf"], timeout=3)

        r["frames_processed"] += 1
        lat = float(vision.get("latency_ms", 0.0))
        r["latencies"].append(lat)
        r["latencies"] = r["latencies"][-50:]
        dets = vision.get("detections", [])
        if dets and len(r["findings"]) < 6:
            top = max(dets, key=lambda d: d.get("conf", 0.0))
            if not r["findings"] or (time.time() - r["findings"][-1]["ts"] > 4.0):
                r["findings"].append({
                    "id": f"FND-{len(r['findings'])+1:02d}",
                    "ts": time.time(),
                    "conf": top["conf"],
                    "location": r["suspected_location"],
                    "morphology": "Candidate Polyp (CADe Only)",
                    "pathology": "PENDING",
                    "status": "pending",
                    "thumb_b64": vision.get("overlay_jpg_b64", ""),
                })
                await _broadcast(code, ["doctor"], {"type": "findings_updated", "findings": r["findings"]})

        await _broadcast(code, ["admin"], {"type": "frame_status", "frames_processed": r["frames_processed"], "latency_ms": lat})
        await _broadcast(code, ["doctor"], {
            "type": "hud_frame",
            "overlay_jpg_b64": vision.get("overlay_jpg_b64", ""),
            "device": vision.get("device", "NVIDIA L4"),
            "latency_ms": lat,
            "count": vision.get("count", 0),
            "detections": dets,
            "frames_processed": r["frames_processed"],
            "source": msg.get("source", "live"),
        })
    except Exception as exc:
        logging.getLogger("clinical").warning(json.dumps({"event": "ai_degraded", "error_type": type(exc).__name__}))
        await _broadcast(code, ["doctor", "admin"], {"type": "ai_degraded", "message": "AI unavailable. Review the live feed manually."})
    finally:
        if r:
            r["in_flight"] = False

@app.websocket("/ws/v2/{code}/{role}")
async def ws_room(ws: WebSocket, code: str, role: str):
    if await pairing_locked(ws.state.clinician_email, code):
        await ws.close(code=1008)
        return
    if code not in ROOMS or pairing_expired(ws.state.clinician_email, ROOMS[code]) or role not in ("admin", "phone", "doctor"):
        await ws.close(code=4004)
        return
    paired_actors.setdefault(code, set()).add(ws.state.clinician_email)
    await ws.accept()
    SOCKETS[code][role].append(ws)
    r = ROOMS[code]
    if role == "phone":
        r["phone_connected"] = True
        await _broadcast(code, ["admin", "doctor"], {"type": "phone_status", "connected": True})
    try:
        while True:
            msg = await ws.receive_json()
            if role == "phone" and msg.get("type") == "frame":
                # Strict rule: Live feed & AI overlay run ONLY after Doctor clicks Start
                try:
                    decode_frame(msg.get("image_b64"))
                except HTTPException:
                    await ws.close(code=1009)
                    return
                if not r["doctor_started"]:
                    await _broadcast(code, ["admin", "doctor"], {"type": "standby_heartbeat", "phone_connected": True})
                    continue
                if r.get("in_flight"):
                    continue  # Depth-1 drop to keep latency crisp
                r["in_flight"] = True
                asyncio.create_task(_process_phone_frame(code, msg))
    except WebSocketDisconnect:
        pass
    finally:
        if ws in SOCKETS[code][role]:
            SOCKETS[code][role].remove(ws)
        if role == "phone" and not SOCKETS[code]["phone"]:
            r["phone_connected"] = False
            r["in_flight"] = False
            await _broadcast(code, ["admin", "doctor"], {"type": "phone_status", "connected": False})

# ---- Phase 2: Longitudinal Patient History & Pathology Reconciliation Registry ----
class PathologySignoffReq(BaseModel):
    diagnosis: str = Field(min_length=1, max_length=2000)
    dysplasia_grade: Optional[str] = Field(None, max_length=100)
    margins: Optional[str] = Field(None, max_length=200)
    icd_o_code: Optional[str] = Field(None, max_length=32)

PATIENT_REGISTRY: Dict[str, Dict[str, Any]] = {
    "DEMO-PATIENT-01": {
        "patient_id": "DEMO-PATIENT-01",
        "abha_id": "ABHA-HASH-677466",
        "hospital_id": TENANT,
        "encounters": [
            {
                "encounter_id": "ENC-2025-0814",
                "procedure_id": "PROC-20250814-118240",
                "date": "2025-08-14",
                "endoscopist_id": "DR-GOKUL-R",
                "hospital_id": TENANT,
                "indication": "Screening Colonoscopy (Age 50)",
                "withdrawal_time_seconds": 580,
                "bbps_scores": {"right": 3, "transverse": 3, "left": 2, "total": 8, "adequate": True},
                "findings": [
                    {
                        "finding_id": "FND-2025-01",
                        "episode_id": "EPISODE-01",
                        "timestamp": "2025-08-14T10:14:22Z",
                        "location": "Cecum / Ascending",
                        "size_mm": 7.0,
                        "morphology": "Paris 0-Is (Sessile)",
                        "physician_decision": "accepted",
                        "evidence_frame_url": "/api/v2/demo-videos/1_35.avi/frame?idx=0",
                        "pathology_status": "SIGNED",
                        "pathology_result": {
                            "signed_by": "DR-PATH-RAMESH-V",
                            "signed_at": "2025-08-19T14:30:00Z",
                            "diagnosis": "Tubular Adenoma with Low-Grade Dysplasia",
                            "dysplasia_grade": "Low-Grade",
                            "margins": "Negative / Clear (R0 Resection)",
                            "icd_o_code": "8211/0",
                        },
                        "surveillance_recommendation": "7-10 years (USMSTF 2020: 1 small tubular adenoma <10mm, completely resected)",
                    }
                ],
                "clinical_narrative": "Screening colonoscopy revealed adequate bowel prep (BBPS 8/9). Single 7mm sessile lesion in cecum removed via cold snare. Pathology confirmed Tubular Adenoma with low-grade dysplasia and clear margins.",
            }
        ]
    },
    "DEMO-PATIENT-02": {
        "patient_id": "DEMO-PATIENT-02",
        "abha_id": "ABHA-HASH-DEMO-02",
        "hospital_id": TENANT,
        "encounters": [{
            "encounter_id": "ENC-DEMO-02",
            "procedure_id": "PROC-DEMO-02",
            "date": "2025-09-02",
            "hospital_id": TENANT,
            "findings": [],
        }],
    },
    "PATIENT-MUMBAI-99": {
        "patient_id": "PATIENT-MUMBAI-99",
        "abha_id": "ABHA-HASH-MUMBAI-99",
        "hospital_id": "HOSP-MUMBAI-02",
        "encounters": [
            {
                "encounter_id": "ENC-MUMBAI-01",
                "procedure_id": "PROC-MUMBAI-001",
                "date": "2026-01-10",
                "endoscopist_id": "DR-SHAH-K",
                "hospital_id": "HOSP-MUMBAI-02",
                "indication": "Diagnostic Colonoscopy",
                "findings": [],
            }
        ]
    }
}

@app.get("/api/v2/patients/{patient_id}/history")
def get_patient_history(
    patient_id: str,
    x_hospital_id: Optional[str] = Header(TENANT)
):
    if patient_id not in PATIENT_REGISTRY:
        raise HTTPException(404, "Patient not found")
    patient = PATIENT_REGISTRY[patient_id]
    if patient["hospital_id"] != x_hospital_id:
        raise HTTPException(
            status_code=403,
            detail="Cross-hospital data boundary violation"
        )

    return pathology_journal.entries(patient)

@app.post("/api/v2/findings/{finding_id}/pathology")
def sign_pathology_result(finding_id: str, req: PathologySignoffReq, request: Request):
    for p_id, p_data in PATIENT_REGISTRY.items():
        if p_data.get("hospital_id") != TENANT:
            continue
        for enc in p_data.get("encounters", []):
            for f in enc.get("findings", []):
                if f["finding_id"] == finding_id:
                    entry = {
                        "signed_by": request.state.clinician_email,
                        "signed_at": datetime.datetime.now(datetime.timezone.utc).isoformat(),
                        "diagnosis": req.diagnosis,
                        "dysplasia_grade": req.dysplasia_grade,
                        "margins": req.margins,
                        "icd_o_code": req.icd_o_code,
                    }
                    if "adenoma" in req.diagnosis.lower():
                        recommendation = "7-10 years (USMSTF 2020: 1-2 small adenomas <10mm, histology confirmed)"
                    elif "hyperplastic" in req.diagnosis.lower() or "serrated" in req.diagnosis.lower():
                        recommendation = "10 years (USMSTF 2020: hyperplastic/serrated polyp <10mm)"
                    else:
                        recommendation = "5-10 years (histology confirmed)"
                    pathology_journal.append(p_data, f, entry, recommendation)
                    saved = pathology_journal.entries(p_data)
                    f = next(item for visit in saved["encounters"] for item in visit["findings"]
                             if item["finding_id"] == finding_id)
                    return {
                        "ok": True,
                        "finding_id": finding_id,
                        "reconciled": True,
                        "earlier_decision_preserved": f["physician_decision"],
                        "finding": f,
                    }
    raise HTTPException(status_code=404, detail=f"Finding '{finding_id}' not found in registry")

# ---- Phase 2: Runs, Job History & Federated Learning Curation Registry ----
class RunReviewReq(BaseModel):
    decision: str  # "accepted" | "dismissed"
    reason: Optional[str] = ""
    reviewer_id: Optional[str] = "DR-GOKUL-R"

PRESEEDED_RUNS: List[Dict[str, Any]] = [
    {
        "run_id": "2abe559e",
        "timestamp": "2026-02-18T09:42:15Z",
        "input_clip": "ldpolyp_clip01.mp4",
        "model": "pvt_pranet_v1",
        "threshold": 0.45,
        "frames_total": 944,
        "frames_flagged": 932,
        "fps": 37.97,
        "execution_worker": "Cloud Run NVIDIA L4",
        "status": "COMPLETED",
        "review_status": "accepted",
        "fl_eligible": True,
        "media_url": "/api/v2/demo-videos/ldpolyp_clip01.mp4",
        "hospital_id": TENANT,
        "clinician_label": "accepted",
        "clinician_notes": "High fidelity mucosal boundary segmentation on ascending colon polyp.",
        "reviewer_id": "DR-GOKUL-R",
        "reviewed_at": "2026-02-18T10:00:00Z",
        "flagged_evidence": [
            {"frame_idx": 42, "conf": 0.94, "box": [120, 85, 230, 210], "evidence_url": "/api/v2/demo-videos/ldpolyp_clip01.mp4"},
            {"frame_idx": 115, "conf": 0.92, "box": [122, 88, 228, 208], "evidence_url": "/api/v2/demo-videos/ldpolyp_clip01.mp4"}
        ],
        "gcs_media_uri": f"gs://{GCS_BUCKET}/demo_videos/ldpolyp_clip01.mp4",
        "gcs_evidence_uris": [
            f"gs://{GCS_BUCKET}/run_logs/2abe559e_evidence_f42.jpg",
            f"gs://{GCS_BUCKET}/run_logs/2abe559e_evidence_f115.jpg"
        ],
    },
    {
        "run_id": "d80e0cd7",
        "timestamp": "2026-02-19T14:15:30Z",
        "input_clip": "sun_seg_seq01.mp4",
        "model": "sam_hq",
        "threshold": 0.50,
        "frames_total": 512,
        "frames_flagged": 488,
        "fps": 28.40,
        "execution_worker": "Cloud Run NVIDIA L4",
        "status": "COMPLETED",
        "review_status": "pending",
        "fl_eligible": False,
        "media_url": "/api/v2/demo-videos/sun_seg_seq01.mp4",
        "hospital_id": TENANT,
        "clinician_label": None,
        "clinician_notes": None,
        "reviewer_id": None,
        "reviewed_at": None,
        "flagged_evidence": [
            {"frame_idx": 18, "conf": 0.89, "box": [140, 110, 260, 240], "evidence_url": "/api/v2/demo-videos/sun_seg_seq01.mp4"}
        ],
        "gcs_media_uri": f"gs://{GCS_BUCKET}/demo_videos/sun_seg_seq01.mp4",
        "gcs_evidence_uris": [
            f"gs://{GCS_BUCKET}/run_logs/d80e0cd7_evidence_f18.jpg"
        ],
    },
    {
        "run_id": "0273f6f9",
        "timestamp": "2026-02-20T11:05:48Z",
        "input_clip": "1_35.avi",
        "model": "sepnet",
        "threshold": 0.40,
        "frames_total": 820,
        "frames_flagged": 745,
        "fps": 42.15,
        "execution_worker": "Cloud Run NVIDIA L4",
        "status": "COMPLETED",
        "review_status": "accepted",
        "fl_eligible": True,
        "media_url": "/api/v2/demo-videos/1_35.avi",
        "hospital_id": TENANT,
        "clinician_label": "accepted",
        "clinician_notes": "Sharp delineation of Paris 0-Is flat lesion; optimal candidate for FL round 3.",
        "reviewer_id": "DR-GOKUL-R",
        "reviewed_at": "2026-02-20T12:00:00Z",
        "flagged_evidence": [
            {"frame_idx": 0, "conf": 0.87, "box": [110, 95, 230, 215], "evidence_url": "/api/v2/demo-videos/1_35.avi/frame?idx=0"}
        ],
        "gcs_media_uri": f"gs://{GCS_BUCKET}/demo_videos/1_35.avi",
        "gcs_evidence_uris": [
            f"gs://{GCS_BUCKET}/run_logs/0273f6f9_evidence_f0.jpg"
        ],
    },
]

RUN_LOGS: Dict[str, Dict[str, Any]] = {}

def _init_run_logs():
    for r in PRESEEDED_RUNS:
        RUN_LOGS[r["run_id"]] = dict(r)
    try:
        st = storage.Client(project=PROJECT)
        bucket = st.bucket(GCS_BUCKET)
        blobs = list(st.list_blobs(bucket, prefix="run_logs/"))
        for b in blobs:
            if b.name.endswith(".json"):
                try:
                    data = json.loads(b.download_as_text())
                    if "run_id" in data and data.get("hospital_id") == TENANT:
                        RUN_LOGS[data["run_id"]] = data
                except Exception:
                    pass
    except Exception:
        pass

_init_run_logs()

def _save_run_log(run: Dict[str, Any]):
    run_id = run["run_id"]
    RUN_LOGS[run_id] = run
    try:
        st = storage.Client(project=PROJECT)
        blob = st.bucket(GCS_BUCKET).blob(f"run_logs/{run_id}.json")
        blob.upload_from_string(json.dumps(run, indent=2), content_type="application/json")
    except Exception:
        pass

def _record_test_frame_run(room: Dict[str, Any], filename: str, result: Dict[str, Any]) -> str:
    new_run_id = uuid.uuid4().hex[:8]
    now_iso = datetime.datetime.now(datetime.timezone.utc).isoformat()
    dets = result.get("detections", [])
    flagged_cnt = len(dets) if dets else (1 if result.get("count", 0) > 0 else 0)
    lat = float(result.get("latency_ms", 22.4))
    fps_val = round(1000.0 / lat, 2) if lat > 0 else 44.6
    media_url = f"/api/v2/demo-videos/{filename}" if filename in ["ldpolyp_clip01.mp4", "sun_seg_seq01.mp4", "1_35.avi", "1_1.avi", "1_11.avi"] else None

    run_record = {
        "run_id": new_run_id,
        "timestamp": now_iso,
        "input_clip": filename,
        "model": room.get("model", "yolovit_yolo"),
        "threshold": float(room.get("conf", 0.45)),
        "frames_total": 1,
        "frames_flagged": flagged_cnt,
        "fps": fps_val,
        "execution_worker": result.get("device", "Cloud Run NVIDIA L4"),
        "status": "COMPLETED",
        "review_status": "pending",
        "fl_eligible": False,
        "media_url": media_url,
        "hospital_id": TENANT,
        "clinician_label": None,
        "clinician_notes": None,
        "reviewer_id": None,
        "reviewed_at": None,
        "flagged_evidence": [
            {
                "frame_idx": 0,
                "conf": d.get("conf", room.get("conf", 0.45)),
                "box": d.get("box", [100, 100, 200, 200]),
                "evidence_url": media_url,
            }
            for d in dets
        ] if dets else ([{
            "frame_idx": 0,
            "conf": 0.85,
            "box": [110, 95, 230, 215],
            "evidence_url": media_url,
        }] if flagged_cnt > 0 else []),
        "gcs_media_uri": f"gs://{GCS_BUCKET}/demo_videos/{filename}",
        "gcs_evidence_uris": [f"gs://{GCS_BUCKET}/run_logs/{new_run_id}_evidence_f0.jpg"] if flagged_cnt > 0 else [],
    }
    _save_run_log(run_record)
    return new_run_id

def _record_procedure_run(room: Dict[str, Any], approved: List[Dict[str, Any]], mean_lat: float, gcs_uri: Optional[str]) -> str:
    new_run_id = uuid.uuid4().hex[:8]
    now_iso = datetime.datetime.now(datetime.timezone.utc).isoformat()
    f_total = room.get("frames_processed", 0) or 1
    f_flagged = len(approved) or len(room.get("findings", []))
    fps_val = round(1000.0 / mean_lat, 2) if mean_lat > 0 else 35.7
    proc_run = {
        "run_id": new_run_id,
        "timestamp": now_iso,
        "input_clip": f"procedure_{room['procedure_id']}.mp4",
        "model": room.get("model", "yolovit_yolo"),
        "threshold": float(room.get("conf", 0.45)),
        "frames_total": f_total,
        "frames_flagged": f_flagged,
        "fps": fps_val,
        "execution_worker": "Cloud Run NVIDIA L4" if room.get("worker") == "cloud_run_l4" else "CPU Preview Mode",
        "status": "COMPLETED",
        "review_status": "accepted" if approved else "pending",
        "fl_eligible": True if approved else False,
        "media_url": gcs_uri,
        "hospital_id": TENANT,
        "procedure_id": room["procedure_id"],
        "clinician_label": "accepted" if approved else None,
        "clinician_notes": f"Procedure {room['procedure_id']} ended with {len(approved)} approved findings.",
        "reviewer_id": room.get("endoscopist_id", "DR-GOKUL-R") if approved else None,
        "reviewed_at": now_iso if approved else None,
        "flagged_evidence": [
            {
                "finding_id": f.get("id"),
                "conf": f.get("conf", 0.8),
                "location": f.get("location"),
                "status": f.get("status"),
            }
            for f in room.get("findings", [])
        ],
        "gcs_media_uri": gcs_uri,
        "gcs_evidence_uris": [gcs_uri] if gcs_uri else [],
    }
    _save_run_log(proc_run)
    return new_run_id

@app.get("/api/v2/runs")
def get_runs():
    runs = [r for r in RUN_LOGS.values() if r.get("hospital_id") == TENANT]
    return {"runs": runs, "total": len(runs)}

@app.get("/api/v2/runs/export-fl-manifest")
def export_fl_manifest(hospital_id: Optional[str] = TENANT):
    if hospital_id != TENANT:
        raise HTTPException(403, "Tenant mismatch")
    lines = []
    for r in RUN_LOGS.values():
        if r.get("fl_eligible") or r.get("review_status") in ("accepted", "dismissed"):
            if r.get("hospital_id") != TENANT:
                continue
            media_uri = r.get("gcs_media_uri") or f"gs://{GCS_BUCKET}/demo_videos/{r.get('input_clip') or (r['run_id'] + '.mp4')}"
            manifest_item = {
                "run_id": r["run_id"],
                "hospital_id": r.get("hospital_id", TENANT),
                "timestamp": r.get("timestamp"),
                "model_id": r.get("model"),
                "decision": r.get("review_status") or r.get("clinician_label") or "accepted",
                "clinician_notes": scrub_phi(r.get("clinician_notes") or ""),
                "input_clip": r.get("input_clip"),
                "gcs_media_uri": media_uri,
                "frames_total": r.get("frames_total", 0),
                "frames_flagged": r.get("frames_flagged", 0),
                "fps": r.get("fps", 30.0),
                "fl_eligible": True,
                "evidence_uris": r.get("gcs_evidence_uris") or [
                    f"gs://{GCS_BUCKET}/run_logs/{r['run_id']}_evidence.jpg"
                ],
                "anonymized_metadata": {
                    "zero_phi": True,
                    "reviewed": bool(r.get("reviewer_id")),
                    "fl_curation_round": "FL-CYCLE-2026-Q1",
                },
            }
            lines.append(json.dumps(manifest_item))

    content = "\n".join(lines) + ("\n" if lines else "")
    return Response(
        content=content,
        media_type="application/x-jsonlines",
        headers={
            "Content-Disposition": "attachment; filename=chakra_fl_dataset_manifest.jsonl",
            "Content-Type": "application/x-jsonlines; charset=utf-8",
        },
    )

@app.get("/api/v2/runs/{run_id}")
def get_run(run_id: str):
    if run_id not in RUN_LOGS:
        try:
            st = storage.Client(project=PROJECT)
            blob = st.bucket(GCS_BUCKET).blob(f"run_logs/{run_id}.json")
            if blob.exists():
                data = json.loads(blob.download_as_text())
                if data.get("hospital_id") == TENANT and data.get("run_id") == run_id:
                    RUN_LOGS[run_id] = data
                    return data
        except Exception:
            pass
        raise HTTPException(status_code=404, detail=f"Run '{run_id}' not found")
    if RUN_LOGS[run_id].get("hospital_id") != TENANT:
        raise HTTPException(404, "Unknown run")
    return RUN_LOGS[run_id]

@app.post("/api/v2/runs/{run_id}/review")
def review_run(run_id: str, req: RunReviewReq, request: Request):
    if RUN_LOGS.get(run_id, {}).get("hospital_id") != TENANT:
        raise HTTPException(status_code=404, detail=f"Run '{run_id}' not found")
    decision = req.decision.lower().strip()
    if decision not in ("accepted", "dismissed"):
        raise HTTPException(status_code=400, detail="Decision must be 'accepted' or 'dismissed'")
    r = RUN_LOGS[run_id]
    clean_notes = scrub_phi(req.reason or "")
    clean_reviewer = request.state.clinician_email
    r["review_status"] = decision
    r["clinician_label"] = decision
    r["clinician_notes"] = clean_notes
    r["reviewer_id"] = clean_reviewer
    r["reviewed_at"] = datetime.datetime.now(datetime.timezone.utc).isoformat()
    r["fl_eligible"] = True
    _save_run_log(r)
    return {"ok": True, "run": r}

from evaluation_map import router as evaluation_map_router
app.include_router(evaluation_map_router)

from clinical_access import ClinicalAccess
app.add_middleware(ClinicalAccess)
