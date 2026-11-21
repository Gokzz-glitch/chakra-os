PROJECT: CHAKRA GI Clinical OS (V2) — Final Release & Submission Build
CONTEXT: Read ADVERSARIAL_REVIEW_REPORT.md, SUBMISSION_PACK.md, and README.md.

EXECUTE THESE 4 TASKS IN ORDER:
1. APPLY TOP CONSENSUS FIXES & FINAL POLISH:
   - Fix only Blocker/Major items from ADVERSARIAL_REVIEW_REPORT.md.
   - Ensure /v2/admin, /v2/phone, and /v2/doctor use the clean Black & White Gmail-style UI (#FFFFFF canvas, #F6F8FC rail, #111827 ink).
   - Update Medtronic GI Genius pricing in SUBMISSION_PACK.md and README.md from "$100,000+" to "~$20K-$30K/yr SaaS (~$40K-$50K CapEx)".
   - Re-run `python -m pytest -v tests/test_chakra_v2.py` and confirm 100% pass.

2. BUILD & RUN HYBRID LOCAL + CLOUD STRESS TEST (tests/run_5video_benchmark.py):
   - Test BOTH local server (http://127.0.0.1:8080) AND live Cloud Run (https://chakra-os-219670109842.asia-south1.run.app).
   - Iterate across ALL models in /api/v2/catalog and AT LEAST 5 staged GCS videos (ldpolyp_clip01.mp4, sun_seg_seq01.mp4, 1_35.avi, 1_1.avi, 1_11.avi).
   - For each run, test: frame/video fetch, L4 inference latency, Gemini 3.8 Flash voice parsing & EN/TA discharge, Gemini TTS audio generation, and HITL BigQuery sign-off.
   - Save full pass/fail matrix and latency stats to BENCHMARK_REPORT.md.

3. GENERATE FINAL PITCH DECK (CHAKRA_Buildathon_Final.pptx):
   - Install python-pptx if missing and write build_ppt.py to generate a crisp, minimalist Black & White clinical deck (10 slides):
     1. Title & Live URLs
     2. Problem (India CRC mortality, 26% adenoma / 34% flat miss rate, reporting burden)
     3. Solution (Day-1 Non-SaMD Clinical OS + Isolated White-Light CADe)
     4. Live 3-Screen Workflow (/v2/admin -> /v2/phone -> /v2/doctor)
     5. Dual-Region Google Cloud Architecture (asia-south1 MeitY + asia-southeast1 L4 GPU + Vertex AI + BigQuery MCP)
     6. Real Benchmark Results (pulled directly from BENCHMARK_REPORT.md across 5+ videos & all models)
     7. Clinical Safety & Regulatory Posture (Standby Gate, PENDING_HISTOPATHOLOGY, mandatory HITL, CDSCO Class B)
     8. Market Viability & Unit Economics (<$0.01/case vs ~$20K-$30K/yr OEM towers)
     9. Roadmap (Apache 2.0 RF-DETR-Small + MedGemma 1.5 4B + Chennai hospital validation)
     10. Team & Call to Action

4. FINAL CLOUD RUN DEPLOY & LIVE SMOKE CHECK:
   - Redeploy chakra-os to asia-south1 (--service-account=chakra-review-runtime@girpolypposframesrealcolon.iam.gserviceaccount.com --max-instances=1 --timeout=3600).
   - Verify live HTTP 200 on /v2/admin, /v2/phone, /v2/doctor, /api/v2/demo-videos, and /api/v2/analytics.
