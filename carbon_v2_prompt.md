PROJECT: CHAKRA GI Clinical OS (V2) on GCP girpolypposframesrealcolon (asia-south1 chakra-os + asia-southeast1 L4 chakra-vision).

TASKS:
1. FIX VIDEO STREAMING & LATENCY:
   - Add GET /api/v2/demo-videos listing gs://girpolypposframesrealcolon-chakra-models/demo_videos/ and GET /api/v2/demo-videos/{name} with Range/206 streaming (for .mp4) and OpenCV/frame-extract fallback for 1_35.avi.
   - Harden WebSocket /ws/v2/{code}/{role} so depth-1 frame dropping never stalls L4 inference.
2. WRITE & RUN CONSOLE TEST SUITE (tests/test_chakra_v2.py):
   - Test room creation (6-digit code), Standby Gate (no overlay before doctor-start), L4 inference, Gemini 3.8 Flash voice parsing + zero-PHI scrubbing, HITL 400-block without attestation, BigQuery commit, and GCS path-traversal/XSS security.
   - Run pytest -v in console and fix all failures until 100% pass.
3. DEPLOY & VERIFY LIVE:
   - Redeploy chakra-os to asia-south1 (--service-account=chakra-review-runtime@girpolypposframesrealcolon.iam.gserviceaccount.com --max-instances=1 --timeout=3600) and curl-verify all live endpoints.
4. PREPARE BUILDATHON SUBMISSION PACK (create SUBMISSION_PACK.md & README.md):
   - Include: Live URLs (/v2/admin, /v2/phone, /v2/doctor), Architecture Diagram (Mermaid), Evaluator Rubric Mapping (Founder Profile, Product Potential, Market Viability, Technical Architecture, Use of Google AI), Pytest pass summary, and a crisp 3-minute live demo script.
