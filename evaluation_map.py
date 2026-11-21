"""Public research-cohort totals; media access is checked separately by Google Cloud IAM."""
from concurrent.futures import ThreadPoolExecutor
import datetime
import json
import os
from pathlib import Path
import re
from threading import Lock
import time

from fastapi import APIRouter, HTTPException
from fastapi.responses import FileResponse, JSONResponse
from google.cloud import storage

router = APIRouter()
batch = "chakra-mixed-evaluation-kkq65"
models = ["yolovit_vit", "chakranet", "pvt_pranet", "sepnet"]
cohort = json.loads(Path("static/cohort-index.json").read_text(encoding="utf-8-sig"))
patients = {r["patient_id"]: r for r in cohort}
receipt_path = re.compile(r"evaluation-runs/(SIM-\d{3})/(yolovit_vit|chakranet|pvt_pranet|sepnet)/"+batch+r"/complete\.json")
lock = Lock()
cache = {}
last_check = 0
snapshot = None

@router.get("/v2/assets/evaluation-galaxy.js")
def script():
    return FileResponse("static/evaluation-galaxy.js", media_type="text/javascript")

def read_receipt(blob):
    match = receipt_path.fullmatch(blob.name)
    patient, model = match.groups()
    data = json.loads(blob.download_as_bytes(if_generation_match=blob.generation,timeout=12))
    if (data["patient_id"],data["model"],data["run_id"],data["frames"],data["skipped"],data["threshold"]) != (patient,model,batch,patients[patient]["frames"],0,.7):
        raise ValueError("Unexpected completion record")
    return {"patient":patient,"model":model,"frames":data["frames"],"flagged":data["flagged_frames"],
            "seconds":round(data["elapsed_seconds"],2),"device":data.get("compute_device","cuda"),
            "completed":data["completed_at"],"files":list(data["artifacts"])}

@router.get("/api/v2/evaluation/live")
def live():
    global last_check,snapshot
    with lock:
        if snapshot is None or time.monotonic()-last_check>=4:
            try:
                bucket=storage.Client().bucket(os.getenv("GCS_BUCKET","girpolypposframesrealcolon-chakra-models"))
                blobs=[b for b in bucket.list_blobs(prefix="evaluation-runs/SIM-",match_glob="**/complete.json",
                             fields="items(name,generation),nextPageToken",timeout=12)
                       if receipt_path.fullmatch(b.name) and receipt_path.fullmatch(b.name)[1] in patients]
                missing=[b for b in blobs if (b.name,b.generation) not in cache]
                with ThreadPoolExecutor(max_workers=16) as pool:
                    for b,result in zip(missing,pool.map(read_receipt,missing)):
                        cache[b.name,b.generation]=result
                snapshot={"patients":cohort,"models":models,"batch":batch,"bucket":bucket.name,
                          "runs":[cache[b.name,b.generation] for b in blobs],
                          "checked":datetime.datetime.now(datetime.timezone.utc).isoformat()}
                last_check=time.monotonic()
            except Exception as exc:
                import logging
                logging.getLogger(__name__).exception("Cloud results refresh failed")
                raise HTTPException(503,"Cloud results temporarily unavailable") from exc
        return JSONResponse(snapshot,headers={"Cache-Control":"no-store"})
