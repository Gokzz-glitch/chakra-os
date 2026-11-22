ADD "RUNS" & "REVIEW" + FEDERATED LEARNING DATASET EXPORT TO LIVE CHAKRA V2 (main.py, admin.html, templates/admin.html):

1. BACKEND APIs IN main.py (persist run logs in GCS bucket gs://girpolypposframesrealcolon-chakra-models/run_logs/ + in-memory cache so history survives Cloud Run restarts):
   - GET /api/v2/runs: Returns all stored backend runs (run_id, timestamp, input_clip, model, threshold, frames_total, frames_flagged, fps, execution_worker, status, review_status, fl_eligible). Pre-seed with the real historical runs (e.g., 2abe559e PVT-PraNet-V1 944 frames / 932 flagged / 37.97 FPS, d80e0cd7 SAM-HQ, 0273f6f9 SEPNet) AND automatically append a new run record every time /api/v2/admin/test-frame or a Doctor procedure completes.
   - GET /api/v2/runs/{run_id}: Returns full run summary, bound media URL (/api/v2/demo-videos/{clip}), and flagged frame evidence.
   - POST /api/v2/runs/{run_id}/review: Saves clinician Accept / Dismiss labels (with reason & zero-PHI anonymized metadata) and marks the run as "fl_eligible: true" for Federated Learning curation.
   - GET /api/v2/runs/export-fl-manifest: Downloads a clean JSONL manifest of all clinician-verified (accepted/dismissed) runs and GCS evidence URIs ready for Federated Learning training rounds (strictly zero-PHI, hospital_id scoped).

2. FRONTEND TABS IN admin.html (and copy to templates/admin.html, keeping Material 3 Light/Dark theme):
   - Add sidebar tab "6. Runs (Job History)": Searchable table of all backend runs (Run ID, Input, Model, Frames/Flagged, FPS, Worker, Review Status) with Refresh button and click-to-open in Review.
   - Add sidebar tab "7. Review & FL Curation": Run selector dropdown, video/frame preview player, Run Summary card (Model, Threshold, Frames, Flagged, FPS, Execution), clinician Accept / Dismiss buttons, and an "Export FL Dataset Manifest (.jsonl)" button.

3. TEST, DEPLOY & PUSH:
   - Run `python -m pytest -v tests/test_chakra_v2.py` to confirm 100% pass.
   - Copy admin.html, doctor.html, and phone.html to templates/ so all templates stay synced.
   - Redeploy chakra-os to asia-south1 (`--service-account=chakra-review-runtime@girpolypposframesrealcolon.iam.gserviceaccount.com --max-instances=1 --timeout=3600 --no-allow-unauthenticated`).
   - Curl-verify GET /api/v2/runs and GET /api/v2/runs/export-fl-manifest on the live URL.
   - Commit and push to https://github.com/Gokzz-glitch/chakra-os (main).
