"""One immutable patient/model run. Publish completion only after every artifact uploads."""
import argparse, contextlib, datetime, hashlib, json, os, subprocess, tempfile, time, zipfile
from pathlib import Path
import cv2
import numpy as np
import torch
from vendor import seg_infer

MODELS = {
    "yolovit_vit": "models/yolovit_vit/VIT.pt",
    "chakranet": "models/chakranet/weights.pth",
    "pvt_pranet": "models/pvt_pranet_v1/weights.pth",
    "sepnet": "models/sepnet/Weight_of_SEPNet.pth",
}
def run(model_key, weights, video, dest, limit=None):
    from shutil import which
    import torch.nn.functional as F
    accelerator=os.getenv("EVAL_DEVICE","cuda")
    if accelerator=="cuda" and not torch.cuda.is_available():
        raise RuntimeError("CUDA unavailable")
    device=torch.device(accelerator)
    if device.type=="cpu":
        torch.set_num_threads(3)
        cv2.setNumThreads(1)
    if model_key=="yolovit_vit":
        from ultralytics import YOLO
        model=YOLO(str(weights))
        if model.task!="detect": raise ValueError("Unexpected checkpoint task")
    else:
        arch=seg_infer.build_model(model_key,Path(__file__).parent/"vendor"/"binary_seg")
        model=seg_infer.load_weights(arch,str(weights),device)
    cap=cv2.VideoCapture(str(video))
    if not cap.isOpened(): raise ValueError("Video open failed")
    w,h=[int(cap.get(k)) for k in (3,4)]
    fps=cap.get(cv2.CAP_PROP_FPS); expected=int(cap.get(cv2.CAP_PROP_FRAME_COUNT))
    mean,std=[torch.tensor(x,device=device).reshape(1,3,1,1) for x in (seg_infer.IMAGENET_MEAN,seg_infer.IMAGENET_STD)]
    ffmpeg=which("ffmpeg")
    if not ffmpeg:
        import imageio_ffmpeg
        ffmpeg=imageio_ffmpeg.get_ffmpeg_exe()
    enc=subprocess.Popen([ffmpeg,"-loglevel","error","-y","-f","rawvideo","-pix_fmt","bgr24","-s",f"{w}x{h}","-r",str(fps),"-i","pipe:0","-vf","pad=ceil(iw/2)*2:ceil(ih/2)*2","-c:v","libx264","-preset","veryfast","-threads","1","-pix_fmt","yuv420p","-movflags","+faststart",str(dest/"replay.mp4")],stdin=subprocess.PIPE)
    count=flags=0; start=time.monotonic()
    try:
        with contextlib.ExitStack() as stack, torch.inference_mode():
            log=stack.enter_context((dest/"frames.jsonl").open("w"))
            masks=stack.enter_context(zipfile.ZipFile(dest/"masks.zip","w",allowZip64=True)) if model_key!="yolovit_vit" else None
            while limit is None or count<limit:
                ok,frame=cap.read()
                if not ok: break
                record={"frame":count,"time_seconds":count/fps}
                if masks is None:
                    pred=model.predict(frame,conf=.70,device=device,verbose=False)[0]
                    boxes=[]
                    for box in pred.boxes:
                        score=float(box.conf.item())
                        if score<=.70: continue
                        xy=box.xyxy[0].tolist(); boxes.append({"xyxy":xy,"confidence":score})
                        x,y,u,v=map(round,xy)
                        cv2.rectangle(frame,(x,y),(u,v),(0,200,255),2)
                        cv2.putText(frame,f"Candidate {score:.2f}",(x,max(18,y-4)),0,.55,(0,200,255),2)
                    record["boxes"]=boxes; flagged=bool(boxes)
                else:
                    x=seg_infer.preprocess(cv2.cvtColor(frame,cv2.COLOR_BGR2RGB),352,device,mean,std,pil=model_key=="sepnet")
                    out=model(x)
                    logits=out[-1] if model_key=="pvt_pranet" else out[0] if isinstance(out,(list,tuple)) else out
                    prob=F.interpolate(logits,size=(h,w),mode="bilinear",align_corners=False).sigmoid()[0,0]
                    mask=(prob>.70).cpu().numpy()
                    record["max_probability"]=float(prob.max()); flagged=bool(mask.any())
                    ok,png=cv2.imencode(".png",mask.astype(np.uint8)*255)
                    if not ok: raise RuntimeError("Mask encoding failed")
                    masks.writestr(f"{count:08}.png",png.tobytes())
                    frame[mask]=(frame[mask]*.45+np.array([68,215,130])*.55).astype(np.uint8)
                flags+=int(flagged); record["flagged"]=flagged
                log.write(json.dumps(record)+"\n");enc.stdin.write(frame.tobytes());count+=1
    finally:
        cap.release();enc.stdin.close();status=enc.wait()
    if status or not count or count!=(min(limit,expected) if limit else expected): raise RuntimeError(f"Incomplete encode {count}/{expected}, ffmpeg={status}")
    return dict(compute_device=str(device),frames=count,skipped=0,flagged_frames=flags,fps=fps,elapsed_seconds=time.monotonic()-start,width=w,height=h,threshold=.70,comparison="strict_greater_than",mode="all_frames",checkpoint_sha256=hashlib.sha256(weights.read_bytes()).hexdigest())
def cloud():
    from google.cloud import storage
    bucket=storage.Client().bucket("girpolypposframesrealcolon-chakra-models")
    rows=json.loads(bucket.blob("evaluation-runs/cohorts/mixed-v1.json").download_as_bytes())
    index=int(os.environ["CLOUD_RUN_TASK_INDEX"])
    if os.getenv("TASK_MAP"):
        assignment=json.loads(bucket.blob(os.environ["TASK_MAP"]).download_as_bytes())
        index=assignment[index]
    model_key=list(MODELS)[index%4]; row=rows[index//4]
    execution=os.getenv("EVAL_BATCH") or os.environ["CLOUD_RUN_EXECUTION"]; prefix=f"evaluation-runs/{row['patient_id']}/{model_key}/{execution}/"
    complete=bucket.blob(prefix+"complete.json")
    if complete.exists(): return
    with tempfile.TemporaryDirectory() as temp:
        path=Path(temp); weights=path/Path(MODELS[model_key]).name; video=path/"input.avi"
        bucket.blob(MODELS[model_key]).download_to_filename(str(weights))
        bucket.blob(row["object"]).download_to_filename(str(video))
        with video.open("rb") as f:
            if hashlib.file_digest(f,"sha256").hexdigest()!=row["sha256"]: raise ValueError("Video hash mismatch")
        result=run(model_key,weights,video,path)
        artifacts={}
        for name in ("replay.mp4","frames.jsonl","masks.zip"):
            if (path/name).exists():
                obj=bucket.blob(prefix+name);obj.upload_from_filename(str(path/name));artifacts[name]=str(obj.generation)
        result.update(patient_id=row["patient_id"],source_sha256=row["sha256"],original=row["object"],model=model_key,run_id=execution,worker_execution=os.environ["CLOUD_RUN_EXECUTION"],artifacts=artifacts,completed_at=datetime.datetime.now(datetime.timezone.utc).isoformat())
        complete.upload_from_string(json.dumps(result),content_type="application/json",if_generation_match=0)
if __name__=="__main__":
    cloud()
