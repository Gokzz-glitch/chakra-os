"""Prepare and verify the private, content-addressed 20/20/20 cohort."""
import csv, hashlib, json, re
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path
from google.cloud import storage
import cv2

ROOT=Path(r"J:\My Drive\video_datasets_polyp_for_gradio_app")
OUT=Path(__file__).parent
BUCKET="girpolypposframesrealcolon-chakra-models"
hyper=ROOT/"hyper-kvasir-videos"/"hyper-kvasir-videos"
with (hyper/"video-annotations.csv").open(encoding="utf-8-sig") as stream:
    annotated={row["videoID"]:row["finding"] for row in csv.DictReader(stream,delimiter=";")}
groups=[]
for folder,label in [("videos with polyps","dataset-labeled polyp"),("videos without polyps","dataset-labeled no polyp")]:
    groups.append([(p,folder,label,folder) for p in (ROOT/folder).rglob("*.avi")])
groups.append([(p,"HyperKvasir","dataset-labeled polyp" if re.search(r"\bpolyps?\b",annotated.get(p.stem,""),re.I) else "other lower-GI annotation",annotated[p.stem]) for p in (hyper/"videos").glob("*.avi") if re.search(r"caec|cecu|sigmoid|colitis|rectum|rectal|colon|ileum|ileoce|divertic|hemorrhoid|haemorrhoid",annotated.get(p.stem,""),re.I) and not re.search(r"post|after|resect",annotated[p.stem],re.I)])
def inspect(item):
    path,source,label,note=item
    with path.open("rb") as f: digest=hashlib.file_digest(f,"sha256").hexdigest()
    cap=cv2.VideoCapture(str(path))
    frames=int(cap.get(cv2.CAP_PROP_FRAME_COUNT)); fps=cap.get(cv2.CAP_PROP_FPS); ok,_=cap.read(); cap.release()
    if not ok or frames<1 or fps<=0: raise ValueError(f"Unreadable video {path.name}")
    return dict(source=source,label=label,annotation=note,relative_path=str(path.relative_to(ROOT)),sha256=digest,frames=frames,fps=fps,bytes=path.stat().st_size,object="evaluation-runs/originals/"+digest+path.suffix.lower())
def upload(row):
    bucket=storage.Client(project="girpolypposframesrealcolon").bucket(BUCKET)
    blob=bucket.blob(row["object"])
    from google.api_core.exceptions import PreconditionFailed
    try:
        blob.metadata={"sha256":row["sha256"]}
        blob.upload_from_filename(str(ROOT/row["relative_path"]),if_generation_match=0,checksum="auto",timeout=600)
    except PreconditionFailed: pass
    blob.reload()
    if (blob.metadata or {}).get("sha256")!=row["sha256"] or blob.size!=row["bytes"]: raise ValueError("Object mismatch")
    return row["patient_id"]
if __name__=="__main__":
    seen=set(); rows=[]
    with ThreadPoolExecutor(max_workers=4) as pool:
        for group in groups:
            ordered=iter(sorted(group,key=lambda item:(item[0].stat().st_size,item[0].name)))
            count=0
            while count<20:
                from itertools import islice
                batch=list(islice(ordered,20-count))
                if not batch: raise ValueError("Insufficient unique originals")
                for row in pool.map(inspect,batch):
                    if row["sha256"] in seen: continue
                    seen.add(row["sha256"]); count+=1
                    row["patient_id"]=f"SIM-{len(rows)+1:03}"
                    rows.append(row)
            print(f"Verified group {len(rows)}/60",flush=True)
        manifest=OUT/"cohort.json"
        manifest.write_text(json.dumps(rows,indent=2))
        for pid in pool.map(upload,rows): print("Private copy",pid,flush=True)
    bucket=storage.Client(project="girpolypposframesrealcolon").bucket(BUCKET)
    bucket.blob("evaluation-runs/cohorts/mixed-v1.json").upload_from_filename(str(manifest))

