PROJECT: CHAKRA GI Clinical OS (V2) in M:\CHAKRA\chakra-buildathon\chakra-os
MISSION: Scope-agnostic GI Reporting OS (Day-1 Non-SaMD Voice + ABDM FHIR R4 + Tamil/English discharge) + isolated White-Light CADe aid (pathology strictly PENDING).

TASKS:
1. BLACK & WHITE GMAIL-STYLE UI (admin.html, phone.html, doctor.html):
   - Pure white canvas (#FFFFFF), soft neutral rail (#F6F8FC), 1px borders (#E2E8F0), charcoal text (#111827), dark pill buttons (#111827). Keep /v1 untouched.
2. CLOUD DEMO VIDEO SELECTOR & CAMERA FIX:
   - Add a "Cloud Demo Clips" dropdown on /v2/admin and /v2/phone calling GET /api/v2/demo-videos (staged: ldpolyp_clip01.mp4, sun_seg_seq01.mp4, 1_35.avi).
   - Filter out OBS Virtual Camera on /v2/phone by default and resize frames to 480px JPEG (0.6 quality).
3. STRICT CLINICAL FLOW:
   - /v2/admin opens first (model, threshold, Cloud Run L4 default, 6-digit code, BigQuery Analytics).
   - /v2/doctor stays in Standby until "Start Procedure" is clicked.
   - "End Procedure & Generate Report" modal shows Gemini 3.8 Flash notes (EN/TA), Gemini TTS audio, ABDM FHIR R4 JSON, mandatory HITL checkbox, and Sign-Off -> BigQuery.
4. UI TESTS: Write tests/test_ui_contract.py verifying all routes and DOM contracts pass with zero JS/HTML errors.
