import asyncio, base64, datetime, os, random, re, tempfile, time, uuid
from typing import Any, Dict, List, Optional
import httpx
from fastapi import FastAPI, File, Form, Header, HTTPException, Request, Response, UploadFile, WebSocket, WebSocketDisconnect
from fastapi.responses import HTMLResponse, RedirectResponse, StreamingResponse, FileResponse
from google.cloud import storage
from pydantic import BaseModel
from clinical_pipeline import (
    build_clinical_report,
    commit_and_query_bq,
    get_bq_analytics,
    parse_voice_note,
    synthesize_discharge_audio,
    upload_evidence_frame,
)

app = FastAPI(title="CHAKRA Clinical OS V2")
VISION_URL = os.getenv("VISION_URL", "https://chakra-vision-219670109842.asia-southeast1.run.app").rstrip("/")
GCS_BUCKET = os.getenv("GCS_BUCKET", "girpolypposframesrealcolon-chakra-models")
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
def _sanitize_video_name(name: str) -> str:
    if not name or ".." in name or "/" in name or "\\" in name or "\x00" in name:
        raise HTTPException(status_code=400, detail="Invalid video name: path traversal blocked")
    if not re.match(r"^[a-zA-Z0-9_\-\.]+\.(mp4|avi)$", name, re.IGNORECASE):
        raise HTTPException(status_code=400, detail="Invalid video name: unsupported extension or illegal characters")
    return name

def _stream_video_direct(clean_name: str, range_header: Optional[str], media_type: str) -> Response:
    """Zero-disk byte-range streaming directly from GCS to prevent Cloud Run tmpfs RAM OOM."""
    local_path = os.path.join(DEMO_CACHE_DIR, clean_name)
    blob = None
    total_size = None
    try:
        st = storage.Client(project=os.getenv("GOOGLE_CLOUD_PROJECT", "girpolypposframesrealcolon"))
        blob = st.bucket(GCS_BUCKET).blob(f"demo_videos/{clean_name}")
        blob.reload()
        total_size = blob.size
    except Exception:
        if os.path.exists(local_path):
            total_size = os.path.getsize(local_path)
        else:
            total_size = 28733

    if not range_header:
        if blob:
            def gcs_stream():
                with blob.open("rb") as f:
                    while chunk := f.read(65536):
                        yield chunk
            return StreamingResponse(
                gcs_stream(),
                status_code=200,
                media_type=media_type,
                headers={"Accept-Ranges": "bytes", "Content-Length": str(total_size), "Content-Type": media_type, "Cache-Control": "public, max-age=3600"}
            )
        elif os.path.exists(local_path):
            def file_stream():
                with open(local_path, "rb") as f:
                    while chunk := f.read(65536):
                        yield chunk
            return StreamingResponse(
                file_stream(),
                status_code=200,
                media_type=media_type,
                headers={"Accept-Ranges": "bytes", "Content-Length": str(total_size), "Content-Type": media_type, "Cache-Control": "public, max-age=3600"}
            )
        else:
            return Response(content=b"", media_type=media_type, headers={"Accept-Ranges": "bytes", "Content-Length": "0"})

    match = re.match(r"^bytes=(\d*)-(\d*)$", range_header.strip())
    if not match:
        raise HTTPException(status_code=416, detail="Range Not Satisfiable", headers={"Content-Range": f"bytes */{total_size}"})

    start_str, end_str = match.groups()
    if start_str and end_str:
        start = int(start_str)
        end = int(end_str)
    elif start_str:
        start = int(start_str)
        end = total_size - 1
    elif end_str:
        suffix = int(end_str)
        start = max(0, total_size - suffix)
        end = total_size - 1
    else:
        raise HTTPException(status_code=416, detail="Range Not Satisfiable", headers={"Content-Range": f"bytes */{total_size}"})

    if start > end or start >= total_size or end >= total_size:
        raise HTTPException(status_code=416, detail="Range Not Satisfiable", headers={"Content-Range": f"bytes */{total_size}"})

    chunk_length = end - start + 1
    if blob:
        data = blob.download_as_bytes(start=start, end=end)
    elif os.path.exists(local_path):
        with open(local_path, "rb") as f:
            f.seek(start)
            data = f.read(chunk_length)
    else:
        data = b"\x00" * chunk_length

    headers = {
        "Content-Range": f"bytes {start}-{end}/{total_size}",
        "Accept-Ranges": "bytes",
        "Content-Length": str(len(data)),
        "Content-Type": media_type,
        "Cache-Control": "public, max-age=3600",
    }
    return Response(content=data, status_code=206, media_type=media_type, headers=headers)

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
            st = storage.Client(project=os.getenv("GOOGLE_CLOUD_PROJECT", "girpolypposframesrealcolon"))
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
    file: UploadFile = File(...),
    bbps_r: int = Form(3), bbps_t: int = Form(3), bbps_l: int = Form(2),
    withdrawal_sec: int = Form(540), endoscopist: str = Form("DR-GOKUL-R")
):
    img_bytes = await file.read()
    vr = await HTTP_CLIENT.post(f"{VISION_URL}/detect", files={"file": (file.filename, img_bytes, file.content_type)})
    vision = vr.json()
    proc_id = f"PROC-{datetime.date.today().strftime('%Y%m%d')}-{uuid.uuid4().hex[:6].upper()}"
    payload = {
        "procedure_id": proc_id, "endoscopist_id": endoscopist,
        "patient_anonymized_id": f"ABHA-HASH-{uuid.uuid4().hex[:6].upper()}",
        "withdrawal_time_seconds": withdrawal_sec,
        "bbps_scores": {"right": bbps_r, "transverse": bbps_t, "left": bbps_l},
        "detections": vision.get("detections", []), "latency_ms": vision.get("latency_ms", 0.0),
    }
    report = build_clinical_report(payload, hitl_approved=False)
    SESSIONS_V1[proc_id] = payload
    return {"vision": vision, "report": report}

@app.post("/api/signoff/{proc_id}")
def v1_signoff(proc_id: str):
    if proc_id not in SESSIONS_V1:
        raise HTTPException(404, "Procedure ID not found")
    payload = SESSIONS_V1[proc_id]
    final_report = build_clinical_report(payload, hitl_approved=True)
    return {"report": final_report, "bigquery": commit_and_query_bq(payload, final_report, hitl_approved=True)}

# ---- V2 Session, Pairing & Clinical Workflow APIs ----
class RoomConfigUpdate(BaseModel):
    model: str = "yolovit_yolo"
    conf: float = 0.45
    worker: str = "cloud_run_l4"
    endoscopist_id: str = "DR-GOKUL-R"
    patient_label: str = "DEMO-PATIENT-01"
    bbps_right: int = 3
    bbps_transverse: int = 3
    bbps_left: int = 2

class VoiceNoteReq(BaseModel):
    transcript: str

class FindingReviewReq(BaseModel):
    finding_id: str
    decision: str  # "accepted" | "dismissed"

class TtsReq(BaseModel):
    text: str
    voice_name: str = "Kore"

class SignoffReq(BaseModel):
    hitl_attested: bool

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
        st = storage.Client(project=os.getenv("GOOGLE_CLOUD_PROJECT", "girpolypposframesrealcolon"))
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
    resp = _stream_video_direct(clean_name, range, media_type)
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
def create_room():
    code = str(random.randint(100000, 999999))
    while code in ROOMS:
        code = str(random.randint(100000, 999999))
    proc_id = f"PROC-{datetime.date.today().strftime('%Y%m%d')}-{code}"
    ROOMS[code] = {
        "code": code,
        "procedure_id": proc_id,
        "patient_anonymized_id": f"ABHA-HASH-{code}",
        "patient_label": "DEMO-PATIENT-01",
        "endoscopist_id": "DR-GOKUL-R",
        "model": "yolovit_yolo",
        "conf": 0.45,
        "worker": "cloud_run_l4",
        "phone_connected": False,
        "doctor_started": False,
        "started_ts": None,
        "withdrawal_sec": 0,
        "bbps_scores": {"right": 3, "transverse": 3, "left": 2},
        "frames_processed": 0,
        "latencies": [],
        "in_flight": False,
        "findings": [],
        "voice_notes": [],
        "suspected_location": "Cecum / Ascending",
        "max_mm": 6.0,
        "last_report": None,
    }
    SOCKETS[code] = {"admin": [], "phone": [], "doctor": []}
    return ROOMS[code]

@app.get("/api/v2/rooms/{code}")
def get_room(code: str):
    if code not in ROOMS:
        raise HTTPException(404, "Pairing code not found")
    r = ROOMS[code]
    return {k: v for k, v in r.items() if k != "in_flight"}

@app.patch("/api/v2/rooms/{code}/config")
async def update_config(code: str, cfg: RoomConfigUpdate):
    if code not in ROOMS:
        raise HTTPException(404, "Pairing code not found")
    r = ROOMS[code]
    r["model"] = cfg.model
    r["conf"] = max(0.1, min(0.95, cfg.conf))
    r["worker"] = cfg.worker
    r["endoscopist_id"] = cfg.endoscopist_id
    r["patient_label"] = cfg.patient_label
    r["bbps_scores"] = {"right": cfg.bbps_right, "transverse": cfg.bbps_transverse, "left": cfg.bbps_left}
    await _broadcast(code, ["admin", "doctor", "phone"], {"type": "config_updated", "config": cfg.model_dump()})
    return {"ok": True, "room": get_room(code)}

@app.post("/api/v2/rooms/{code}/doctor-start")
async def doctor_start(code: str):
    if code not in ROOMS:
        raise HTTPException(404, "Pairing code not found")
    r = ROOMS[code]
    r["doctor_started"] = True
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
            f["status"] = req.decision
            break
    await _broadcast(code, ["admin", "doctor"], {"type": "findings_updated", "findings": r["findings"]})
    return {"ok": True, "findings": r["findings"]}

@app.post("/api/v2/rooms/{code}/voice-note")
async def add_voice_note(code: str, req: VoiceNoteReq):
    if code not in ROOMS:
        raise HTTPException(404, "Pairing code not found")
    r = ROOMS[code]
    parsed = parse_voice_note(req.transcript)
    if parsed.get("bbps_right") is not None: r["bbps_scores"]["right"] = int(parsed["bbps_right"])
    if parsed.get("bbps_transverse") is not None: r["bbps_scores"]["transverse"] = int(parsed["bbps_transverse"])
    if parsed.get("bbps_left") is not None: r["bbps_scores"]["left"] = int(parsed["bbps_left"])
    if parsed.get("suspected_location"): r["suspected_location"] = parsed["suspected_location"]
    if parsed.get("suspected_size_mm"): r["max_mm"] = float(parsed["suspected_size_mm"])
    r["voice_notes"].append(parsed["clinical_note"])
    await _broadcast(code, ["admin", "doctor"], {
        "type": "voice_parsed", "parsed": parsed, "bbps_scores": r["bbps_scores"],
        "suspected_location": r["suspected_location"], "voice_notes": r["voice_notes"]
    })
    return {"ok": True, "parsed": parsed, "bbps_scores": r["bbps_scores"]}

@app.post("/api/v2/rooms/{code}/admin-test-frame")
async def admin_test_frame(code: str, file: UploadFile = File(...)):
    if code not in ROOMS:
        raise HTTPException(404, "Pairing code not found")
    r = ROOMS[code]
    raw = await file.read()
    if r.get("worker") == "cloud_run_l4" and VISION_URL:
        try:
            vr = await HTTP_CLIENT.post(
                f"{VISION_URL}/detect",
                params={"conf": r["conf"]},
                files={"file": (file.filename or "test.jpg", raw, file.content_type or "image/jpeg")},
                timeout=10.0,
            )
            return vr.json()
        except Exception:
            pass
    return {
        "device": "CPU Preview Mode",
        "latency_ms": 14.0,
        "count": 0,
        "detections": [],
        "overlay_jpg_b64": base64.b64encode(raw).decode(),
    }

@app.post("/api/v2/rooms/{code}/end-report")
async def end_and_generate_report(code: str):
    if code not in ROOMS:
        raise HTTPException(404, "Pairing code not found")
    r = ROOMS[code]
    r["doctor_started"] = False
    elapsed = int(time.time() - r["started_ts"]) if r["started_ts"] else 390
    r["withdrawal_sec"] = max(elapsed, 60)
    approved = [f for f in r["findings"] if f.get("status") == "accepted"]
    gcs_uri = None
    if approved and approved[0].get("thumb_b64"):
        gcs_uri = upload_evidence_frame(r["procedure_id"], approved[0]["thumb_b64"])
    mean_lat = round(sum(r["latencies"]) / len(r["latencies"]), 1) if r["latencies"] else 28.0
    payload = {
        "procedure_id": r["procedure_id"],
        "endoscopist_id": r["endoscopist_id"],
        "patient_anonymized_id": r["patient_anonymized_id"],
        "withdrawal_time_seconds": r["withdrawal_sec"],
        "bbps_scores": r["bbps_scores"],
        "approved_findings": [{k: v for k, v in f.items() if k != "thumb_b64"} for f in approved],
        "voice_notes": r["voice_notes"],
        "max_mm": r.get("max_mm"),
        "latency_ms": mean_lat,
        "edge_model": f"{r['model']} ({r['worker']})",
        "evidence_gcs_uri": gcs_uri,
    }
    report = build_clinical_report(payload, hitl_approved=False)
    r["last_payload"] = payload
    r["last_report"] = report
    await _broadcast(code, ["admin", "doctor", "phone"], {"type": "procedure_ended", "procedure_id": r["procedure_id"]})
    return {"report": report, "findings": r["findings"], "withdrawal_sec": r["withdrawal_sec"]}

@app.post("/api/v2/rooms/{code}/tts")
def room_tts(code: str, req: TtsReq):
    if code not in ROOMS:
        raise HTTPException(404, "Pairing code not found")
    return synthesize_discharge_audio(req.text, req.voice_name)

@app.post("/api/v2/rooms/{code}/signoff")
async def room_signoff(code: str, req: SignoffReq):
    if code not in ROOMS:
        raise HTTPException(404, "Pairing code not found")
    if not req.hitl_attested:
        raise HTTPException(400, "Mandatory clinician HITL attestation required before BigQuery commit")
    r = ROOMS[code]
    if not r.get("last_payload"):
        raise HTTPException(400, "Generate report before sign-off")
    final_report = build_clinical_report(r["last_payload"], hitl_approved=True)
    bq_res = commit_and_query_bq(r["last_payload"], final_report, hitl_approved=True)
    await _broadcast(code, ["admin", "doctor"], {"type": "signed_off", "bigquery": bq_res})
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
        if not raw_b64:
            return
        raw = base64.b64decode(raw_b64.split(",")[-1])
        if r["worker"] == "cloud_run_l4" and VISION_URL:
            try:
                vr = await HTTP_CLIENT.post(
                    f"{VISION_URL}/detect",
                    params={"conf": r["conf"]},
                    files={"file": ("frame.jpg", raw, "image/jpeg")},
                    timeout=3.0,
                )
                vision = vr.json()
            except Exception:
                vision = {
                    "device": "NVIDIA L4 (Timeout Fallback)",
                    "latency_ms": 28.0,
                    "count": 0,
                    "detections": [],
                    "overlay_jpg_b64": raw_b64.split(",")[-1],
                }
        else:
            vision = {
                "device": "CPU Preview Mode",
                "latency_ms": 12.0,
                "count": 0,
                "detections": [],
                "overlay_jpg_b64": raw_b64.split(",")[-1],
            }

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
                    "status": "accepted",
                    "thumb_b64": vision.get("overlay_jpg_b64", ""),
                })
                await _broadcast(code, ["admin", "doctor"], {"type": "findings_updated", "findings": r["findings"]})

        await _broadcast(code, ["doctor", "admin"], {
            "type": "hud_frame",
            "overlay_jpg_b64": vision.get("overlay_jpg_b64", ""),
            "device": vision.get("device", "NVIDIA L4"),
            "latency_ms": lat,
            "count": vision.get("count", 0),
            "detections": dets,
            "frames_processed": r["frames_processed"],
            "source": msg.get("source", "live"),
        })
    except Exception:
        pass
    finally:
        if r:
            r["in_flight"] = False

@app.websocket("/ws/v2/{code}/{role}")
async def ws_room(ws: WebSocket, code: str, role: str):
    if code not in ROOMS or role not in ("admin", "phone", "doctor"):
        await ws.close(code=4004)
        return
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
    signed_by: str = "DR-PATH-RAMESH-V"
    diagnosis: str = "Tubular Adenoma with Low-Grade Dysplasia"
    dysplasia_grade: str = "Low-Grade"
    margins: str = "Negative / Clear (R0 Resection)"
    icd_o_code: Optional[str] = "8211/0"

PATIENT_REGISTRY: Dict[str, Dict[str, Any]] = {
    "DEMO-PATIENT-01": {
        "patient_id": "DEMO-PATIENT-01",
        "abha_id": "ABHA-HASH-677466",
        "hospital_id": "HOSP-CHENNAI-01",
        "encounters": [
            {
                "encounter_id": "ENC-2025-0814",
                "procedure_id": "PROC-20250814-118240",
                "date": "2025-08-14",
                "endoscopist_id": "DR-GOKUL-R",
                "hospital_id": "HOSP-CHENNAI-01",
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
    x_hospital_id: Optional[str] = Header("HOSP-CHENNAI-01")
):
    if patient_id not in PATIENT_REGISTRY:
        PATIENT_REGISTRY[patient_id] = {
            "patient_id": patient_id,
            "abha_id": f"ABHA-HASH-{patient_id[-6:]}",
            "hospital_id": x_hospital_id or "HOSP-CHENNAI-01",
            "encounters": []
        }

    patient = PATIENT_REGISTRY[patient_id]
    if patient["hospital_id"] != x_hospital_id:
        raise HTTPException(
            status_code=403,
            detail=f"Cross-hospital data boundary violation: patient records for hospital '{patient['hospital_id']}' are isolated from querying tenant '{x_hospital_id}'"
        )

    return patient

@app.post("/api/v2/findings/{finding_id}/pathology")
def sign_pathology_result(finding_id: str, req: PathologySignoffReq):
    for p_id, p_data in PATIENT_REGISTRY.items():
        for enc in p_data.get("encounters", []):
            for f in enc.get("findings", []):
                if f["finding_id"] == finding_id:
                    f["pathology_status"] = "SIGNED"
                    f["pathology_result"] = {
                        "signed_by": req.signed_by,
                        "signed_at": datetime.datetime.now(datetime.timezone.utc).isoformat(),
                        "diagnosis": req.diagnosis,
                        "dysplasia_grade": req.dysplasia_grade,
                        "margins": req.margins,
                        "icd_o_code": req.icd_o_code,
                    }
                    if "adenoma" in req.diagnosis.lower():
                        f["surveillance_recommendation"] = "7-10 years (USMSTF 2020: 1-2 small adenomas <10mm, histology confirmed)"
                    elif "hyperplastic" in req.diagnosis.lower() or "serrated" in req.diagnosis.lower():
                        f["surveillance_recommendation"] = "10 years (USMSTF 2020: hyperplastic/serrated polyp <10mm)"
                    else:
                        f["surveillance_recommendation"] = "5-10 years (histology confirmed)"
                    return {
                        "ok": True,
                        "finding_id": finding_id,
                        "reconciled": True,
                        "earlier_decision_preserved": f["physician_decision"],
                        "finding": f,
                    }
    raise HTTPException(status_code=404, detail=f"Finding '{finding_id}' not found in registry")
