"""PraNet / PVT-PraNet / ChakraNet video inference worker (runs on the Kaggle GPU, launched by backend.py).

Same contract as video_infer.py: reads --source, writes an annotated video to local scratch,
re-encodes to H.264, moves it to --output, prints `PROGRESS done/total` lines.

PraNet and PVT-PraNet mirror the project's evaluators (MyTest_med.py): BGR->RGB, resize to 352x352,
/255, ImageNet mean/std, take the LAST of the four outputs, resize the logits to the frame size,
sigmoid, threshold the RAW probability.

SEPNet (wangtong627/SEPNet, PVT-v2-b2): PIL-bilinear resize to 352, ImageNet mean/std, output p1, sigmoid, RAW threshold
(upstream min-max stretches each map to [0,1], so its max is always 1 and any threshold flags every frame; not done here).

ChakraNet (adabn-chakranet notebook) uses the same preprocessing, a single logit map, and by default
test-time AdaBN first: all BatchNorm2d running statistics are reset (momentum=None, cumulative average)
and re-estimated by forward passes over unlabelled frames of the video being processed
(notebook defaults: 10 batches x 32 frames), with no backprop, then frozen for inference.
"""
import argparse
import json
import os
import sys
import tempfile
import time
from pathlib import Path

IMAGENET_MEAN = (0.485, 0.456, 0.406)
IMAGENET_STD = (0.229, 0.224, 0.225)
ARCHES = ("pranet", "pvt_pranet", "chakranet", "sepnet")
# SEPNet's released checkpoint is the TRAIN model (with the PSE module); the inference model omits it.
# These are the only keys allowed to be present in the checkpoint but absent from the model.
SEPNET_UNUSED_PREFIXES = ("sc2_block.", "sc3_block.")


def build_model(arch, lib_parent):
    """Import <lib_parent>/lib as a package and construct the network without needing the
    pretrained-backbone files the constructors normally read (the checkpoint overwrites them)."""
    import warnings
    warnings.filterwarnings("ignore")     # the upstream lib triggers harmless timm deprecation noise
    import torch

    lib_parent = Path(lib_parent).resolve()
    if arch == "sepnet":                  # self-contained package binary_seg/sepnet (not under lib/)
        if not (lib_parent / "sepnet" / "model.py").is_file():
            sys.exit(f"ERROR: {lib_parent / 'sepnet' / 'model.py'} not found.")
        sys.path.insert(0, str(lib_parent))
        from sepnet import SEPNet_EvalModel
        return SEPNet_EvalModel(backbone_name="pvt-v2-b2", pretrained_backbone_path=None, mid_channels=64,
                                rf_reduction_scale=4, rf_se_channel_reduction=16, df_channel_reduction=[4, 4],
                                sc_hidden_scale=32, sc_gas_ksize=1, sc_middle_channle_scale=2,
                                sc_ksize=[3, 3, 3], sc_gas_ksize_scale=[15, 15, 15])   # myTest.py defaults
    need = "chakranet.py" if arch == "chakranet" else "PraNet_Res2Net.py"
    if not (lib_parent / "lib" / need).is_file():
        sys.exit(f"ERROR: {lib_parent / 'lib' / need} not found.")
    sys.path.insert(0, str(lib_parent))

    if arch == "chakranet":
        from lib.chakranet import PraNetResNet101
        return PraNetResNet101(channels=64, pretrained_backbone=False)

    from lib import PraNet_Res2Net as mod
    if arch == "pranet":
        real = mod.res2net50_v1b_26w_4s
        mod.res2net50_v1b_26w_4s = lambda pretrained=False, **kw: real(False, **kw)   # skip ImageNet weights download
        return mod.PraNet()
    # PVT_PraNet loads ./models/pvt_v2_b2.pth while being built: give it a random one in a temp dir.
    from lib.pvtv2 import pvt_v2_b2
    old = os.getcwd()
    with tempfile.TemporaryDirectory() as tmp:
        os.makedirs(Path(tmp) / "models")
        torch.save(pvt_v2_b2().state_dict(), Path(tmp) / "models" / "pvt_v2_b2.pth")
        os.chdir(tmp)
        try:
            return mod.PVT_PraNet()
        finally:
            os.chdir(old)


def load_weights(model, path, device):
    import torch

    state = torch.load(path, map_location=device, weights_only=True)
    for key in ("model_state_dict", "state_dict"):      # ChakraNet saves {'epoch','model_state_dict',...}
        if isinstance(state, dict) and key in state:
            state = state[key]
            break
    state = {(k[7:] if k.startswith("module.") else k): v for k, v in state.items()}
    if type(model).__name__ == "SEPNet_EvalModel":
        load_sepnet(model, state)
    else:
        model.load_state_dict(state)          # strict
    return model.to(device).eval()


def load_sepnet(model, state):
    """Strict load with ONE explicit exception: checkpoint keys of the unused PSE module (sc2_block./sc3_block.).
    Anything else missing or unexpected aborts, instead of the upstream silent strict=False."""
    have, want = set(state), set(model.state_dict())
    missing = sorted(want - have)
    unexpected = sorted(k for k in have - want if not k.startswith(SEPNET_UNUSED_PREFIXES))
    if missing or unexpected:
        sys.exit(f"ERROR: SEPNet checkpoint does not match the architecture: {len(missing)} missing "
                 f"(e.g. {missing[:3]}), {len(unexpected)} unexpected (e.g. {unexpected[:3]}).")
    shapes = [k for k in want if tuple(state[k].shape) != tuple(model.state_dict()[k].shape)]
    if shapes:
        sys.exit(f"ERROR: SEPNet shape mismatch in {len(shapes)} tensors (e.g. {shapes[:3]}).")
    skipped = sorted(have - want)
    model.load_state_dict({k: v for k, v in state.items() if k in want})      # now truly strict
    print(f"[SEPNet] strict load OK: {len(want)} tensors; ignored {len(skipped)} PSE (training-only) keys", flush=True)


def preprocess(rgb, size, device, mean, std, pil=False):
    import cv2
    import numpy as np
    import torch

    if pil:    # SEPNet trained/tested with torchvision Resize on PIL images (bilinear, antialiased)
        from PIL import Image
        x = np.asarray(Image.fromarray(rgb).resize((size, size), Image.BILINEAR)).astype(np.float32) / 255.0
    else:
        x = cv2.resize(rgb, (size, size)).astype(np.float32) / 255.0
    x = torch.from_numpy(x).permute(2, 0, 1).unsqueeze(0).to(device)
    return (x - mean) / std


def adabn_adapt(model, source, device, size, mean, std, batches, batch_size, amp):
    """Test-time AdaBN exactly as the notebook's AdaBNAdapter: reset BN stats, momentum=None
    (cumulative average), forward unlabelled target batches in train mode under no_grad, then eval."""
    import cv2
    import torch
    import torch.nn as nn

    cap = cv2.VideoCapture(source)
    total = int(cap.get(cv2.CAP_PROP_FRAME_COUNT) or 0)
    want = batches * batch_size
    step = max(1, total // want) if total else 1
    frames, i = [], 0
    while len(frames) < want:
        ok, frame = cap.read()
        if not ok:
            break
        if i % step == 0:
            frames.append(cv2.cvtColor(cv2.resize(frame, (size, size)), cv2.COLOR_BGR2RGB))
        i += 1
    cap.release()
    if not frames:
        sys.exit("AdaBN: could not read any frames to adapt on.")

    bn = [m for m in model.modules() if isinstance(m, nn.BatchNorm2d)]
    for m in bn:
        m.reset_running_stats()
        m.momentum = None
    model.train()
    t0 = time.time()
    used = 0
    with torch.no_grad():
        for s in range(0, len(frames), batch_size):
            chunk = frames[s:s + batch_size]
            batch = preprocess_batch(chunk, device, mean, std)
            with torch.autocast(device_type="cuda", enabled=amp):
                model(batch)
            used += 1
    model.eval()
    print(f"[AdaBN] reset {len(bn)} BatchNorm2d layers; adapted on {len(frames)} frames "
          f"({used} batches of up to {batch_size}) in {time.time() - t0:.1f}s", flush=True)


def preprocess_batch(frames_rgb, device, mean, std):
    import numpy as np
    import torch

    x = torch.from_numpy(np.stack(frames_rgb).astype(np.float32) / 255.0).permute(0, 3, 1, 2).to(device)
    return (x - mean) / std


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--arch", required=True, choices=ARCHES)
    ap.add_argument("--weights", required=True)
    ap.add_argument("--lib-parent", default=".")
    ap.add_argument("--source", required=True)
    ap.add_argument("--output", required=True)
    ap.add_argument("--device", default="cuda")
    ap.add_argument("--threshold", type=float, default=0.5)
    ap.add_argument("--testsize", type=int, default=352)
    ap.add_argument("--strict-device", action="store_true")
    ap.add_argument("--adabn", choices=("on", "off"), default="on", help="ChakraNet only: test-time AdaBN on the video's own frames")
    ap.add_argument("--adapt-batches", type=int, default=10)
    ap.add_argument("--adapt-batch-size", type=int, default=32)
    ap.add_argument("--classify", choices=("on", "off"), default="off",
                    help="sub-phenotype class per detected frame (polyp_split rules) -> <output>.classes.csv")
    ap.add_argument("--class-thresholds", help="thresholds.json from polyp_split.py (frozen cut-offs); if omitted they are fitted on this run")
    ap.add_argument("--neg-thresholds", help="neg_thresholds.json from neg_split.py (frozen cut-offs for frames WITHOUT a predicted region); "
                                             "if omitted they are fitted on this run's negative frames. Used when --classify on")
    ap.add_argument("--masks", choices=("on", "off"), default="on",
                    help="write the binary prediction as a LOSSLESS FFV1 video (<output>.mask.mkv, 0/255, one frame per input frame) "
                         "and a metrics file (<output>.summary.json)")
    args = ap.parse_args()

    import cv2
    import numpy as np
    import torch
    import torch.nn.functional as F
    from video_infer import finalize, pick_device

    device = pick_device(args.device, args.strict_device)
    cap = cv2.VideoCapture(args.source)
    if not cap.isOpened():
        sys.exit(f"Unable to open video: {args.source}")
    fps = cap.get(cv2.CAP_PROP_FPS) or 25.0
    total = int(cap.get(cv2.CAP_PROP_FRAME_COUNT) or 0)
    w, h = int(cap.get(cv2.CAP_PROP_FRAME_WIDTH)), int(cap.get(cv2.CAP_PROP_FRAME_HEIGHT))
    print(f"Device: {device} | arch {args.arch} | {w}x{h} @ {fps:.1f} fps | {total} frames", flush=True)

    model = load_weights(build_model(args.arch, args.lib_parent), args.weights, device)
    mean = torch.tensor(IMAGENET_MEAN, device=device).view(1, 3, 1, 1)
    std = torch.tensor(IMAGENET_STD, device=device).view(1, 3, 1, 1)
    amp = device != "cpu"       # the notebook ran adaptation and evaluation under autocast
    if args.arch == "chakranet":
        if args.adabn == "on":
            adabn_adapt(model, args.source, device, args.testsize, mean, std, args.adapt_batches, args.adapt_batch_size, amp)
        else:
            print("[AdaBN] off: using the checkpoint's source-domain BatchNorm statistics", flush=True)

    classifier, cls_rows, T_cls = None, [], None
    negc, neg_rows, T_neg = None, [], None
    if args.classify == "on":
        import neg_classify as negc
        import polyp_classify as classifier
        T_neg = negc.load_thresholds(args.neg_thresholds) if args.neg_thresholds else None
        print("[neg-classify] thresholds: " + (f"frozen from {args.neg_thresholds}" if T_neg else
              "will be FITTED on this run's negative frames (dataset-relative; pass --neg-thresholds to freeze)"), flush=True)
        T_cls = classifier.load_thresholds(args.class_thresholds) if args.class_thresholds else None
        print("[classify] thresholds: " + (f"frozen from {args.class_thresholds}" if T_cls else
              "will be FITTED on this run's detections (dataset-relative; pass --class-thresholds to freeze)"), flush=True)

    scratch = Path(tempfile.mkdtemp(prefix="seg_"))
    raw = scratch / "raw.mp4"
    writer = cv2.VideoWriter(str(raw), cv2.VideoWriter_fourcc(*"mp4v"), fps, (w, h))
    if not writer.isOpened():
        sys.exit("Unable to create the output video writer.")
    mask_raw, mask_writer = scratch / "mask.mkv", None
    if args.masks == "on":
        mask_writer = cv2.VideoWriter(str(mask_raw), cv2.VideoWriter_fourcc(*"FFV1"), fps, (w, h), False)
        if not mask_writer.isOpened():
            print("WARNING: this OpenCV build cannot write FFV1; the mask video is skipped.", flush=True)
            mask_writer = None
    done = flagged = 0
    area_sum = conf_sum = 0.0
    t0 = time.time()
    with torch.no_grad():
        while True:
            ok, frame = cap.read()
            if not ok:
                break
            x = preprocess(cv2.cvtColor(frame, cv2.COLOR_BGR2RGB), args.testsize, device, mean, std, pil=args.arch == "sepnet")
            if args.arch == "chakranet":
                with torch.autocast(device_type="cuda", enabled=amp):
                    out = model(x)
                logits = (out[0] if isinstance(out, (tuple, list)) else out).float()
            elif args.arch == "sepnet":
                logits = model(x)[0]
            else:
                logits = model(x)[-1]
            prob = F.interpolate(logits, size=(h, w), mode="bilinear", align_corners=False).sigmoid()[0, 0]
            pm = prob > args.threshold
            mask = pm.cpu().numpy().astype(np.uint8)
            if mask_writer is not None:
                mask_writer.write(mask * 255)
            if mask.any():
                flagged += 1
                area_sum += float(mask.mean())
                conf_sum += float(prob[pm].mean())
                label = None
                if classifier is not None:
                    crow = classifier.frame_descriptors(frame, mask.astype(bool), prob.cpu().numpy())
                    if crow is not None:
                        crow.update(frame=done, time_s=round(done / fps, 3))
                        if T_cls:
                            crow.update(classifier.label_row(crow, T_cls))
                            label = crow["folder"] + (" ?" if crow["review_reasons"] else "")
                        cls_rows.append(crow)
                tint = frame.copy()
                tint[mask > 0] = (0.55 * tint[mask > 0] + 0.45 * np.array((0, 255, 0))).astype(np.uint8)
                contours, _ = cv2.findContours(mask, cv2.RETR_EXTERNAL, cv2.CHAIN_APPROX_SIMPLE)
                cv2.drawContours(tint, contours, -1, (0, 255, 0), 2)
                if label:
                    cv2.putText(tint, label.replace("__", " "), (crow["x0"], max(crow["y0"] - 8, 16)),
                                cv2.FONT_HERSHEY_SIMPLEX, 0.55, (0, 255, 255), 2, cv2.LINE_AA)
                frame = tint
            elif negc is not None:
                nrow = negc.frame_features(frame)
                nrow.update(frame=done, time_s=round(done / fps, 3))
                if T_neg:
                    nrow.update(negc.label_row(nrow, T_neg))
                    cv2.putText(frame, nrow["class_name"], (10, 24), cv2.FONT_HERSHEY_SIMPLEX, 0.6, (255, 200, 0), 2, cv2.LINE_AA)
                neg_rows.append(nrow)
            writer.write(frame)
            done += 1
            if done % 10 == 0 or done == total:
                print(f"PROGRESS {done}/{total or done}", flush=True)
    cap.release()
    writer.release()
    if mask_writer is not None:
        mask_writer.release()
    if done == 0:
        sys.exit("No frames could be read from the video.")
    print(f"PROGRESS {done}/{done}", flush=True)
    print(f"Frames with a predicted region: {flagged}/{done} ({100 * flagged / done:.1f}%)"
          + (f", mean area {100 * area_sum / flagged:.2f}% of the frame" if flagged else "")
          + f" | {done / max(time.time() - t0, 1e-6):.1f} fps", flush=True)
    finalize(raw, Path(args.output))
    print(f"Saved annotated video: {args.output}", flush=True)
    out = Path(args.output)
    if mask_writer is not None and mask_raw.is_file() and mask_raw.stat().st_size > 0:
        import shutil
        shutil.move(str(mask_raw), str(out.with_suffix(".mask.mkv")))
        print(f"Saved lossless mask video (FFV1, 0/255): {out.with_suffix('.mask.mkv')}", flush=True)
    summary = dict(arch=args.arch, threshold=args.threshold, total_frames=done, detected_frames=flagged,
                   detection_ratio=flagged / done, mean_confidence=(conf_sum / flagged if flagged else None),
                   mean_area_pct=(100 * area_sum / flagged if flagged else None),
                   fps=round(done / max(time.time() - t0, 1e-6), 2), video_fps=fps,
                   frame_size=[w, h], classify=args.classify == "on")
    if classifier is not None:
        summary["positive"] = write_classes(classifier, cls_rows, T_cls, out)
    if negc is not None:
        summary["negative"] = write_neg_classes(negc, neg_rows, T_neg, out)
    out.with_suffix(".summary.json").write_text(json.dumps(summary, indent=2), encoding="utf-8")


def write_classes(classifier, rows, T, output):
    import pandas as pd
    if not rows:
        print("[classify] no detections to classify", flush=True)
        return {"rows": 0}
    T_given = T is not None
    if T is None:
        if len(rows) < 30:
            print(f"[classify] WARNING: only {len(rows)} detections to fit thresholds on; quantile cut-offs are unreliable", flush=True)
        T = classifier.fit_thresholds(rows)
        output.with_suffix(".thresholds.json").write_text(json.dumps({"positive": T}, indent=2), encoding="utf-8")
    for r, lab in zip(rows, classifier.label_rows(rows, T)):
        r.update(lab)
    df = pd.DataFrame(rows)
    df.to_csv(output.with_suffix(".classes.csv"), index=False)
    print("[classify] detections per folder:\n" + df["folder"].value_counts().to_string(), flush=True)
    top = df["folder"].value_counts()
    top_class = df["class_name"].value_counts().index[0]
    sub = df[df["class_name"] == top_class].iloc[0]
    return {"rows": int(len(df)), "folders": {k: int(v) for k, v in top.items()}, "dominant_class": top_class,
            "dominant_size": sub["size_cls"], "dominant_morph": sub["morph_cls"], "dominant_bnd": sub["bnd_cls"],
            "needs_review": int((df["review_reasons"] != "").sum()), "thresholds": "frozen" if T_given else "fitted-on-this-run"}


def write_neg_classes(negc, rows, T, output):
    """Frames with no predicted region -> <output>.neg_classes.csv (+ <output>.neg_thresholds.json when fitted on this run)."""
    import pandas as pd
    if not rows:
        print("[neg-classify] no frames without a predicted region", flush=True)
        return {"rows": 0}
    T_given = T is not None
    if T is None:
        if len(rows) < 200:
            print(f"[neg-classify] WARNING: only {len(rows)} negative frames to fit thresholds on; quantile cut-offs are unreliable", flush=True)
        T = {k: float(v) for k, v in negc.fit_thresholds(rows).items() if k in negc.THRESHOLD_KEYS}
        output.with_suffix(".neg_thresholds.json").write_text(json.dumps({"negative": T}, indent=2), encoding="utf-8")
    for r, lab in zip(rows, negc.label_rows(rows, T)):
        r.update(lab)
    df = pd.DataFrame(rows)
    df.to_csv(output.with_suffix(".neg_classes.csv"), index=False)
    print("[neg-classify] frames per negative class:\n" + df["class_name"].value_counts().to_string(), flush=True)
    return {"rows": int(len(df)), "classes": {k: int(v) for k, v in df["class_name"].value_counts().items()},
            "thresholds": "frozen" if T_given else "fitted-on-this-run"}


if __name__ == "__main__":
    sys.exit(main())
