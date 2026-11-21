# CHAKRA GI Clinical OS (V2) — Buildathon Submission Pack

> **Mission:** Scope-Agnostic GI Clinical Operating System combining Day-1 Non-SaMD Voice Documentation, NRCeS ABDM FHIR R4 Reporting, and Bilingual (English/Tamil) Discharge with an Isolated Real-Time White-Light Polyp CADe Visual Aid on Google Cloud Run NVIDIA L4.

---

## 1. Live Deployment URLs

| Component | Target Role / Description | Live URL |
| :--- | :--- | :--- |
| **Backend Console** | Model configuration, 6-digit room pairing, GCS demo video tester, BigQuery analytics | [https://chakra-os-219670109842.asia-south1.run.app/v2/admin](https://chakra-os-219670109842.asia-south1.run.app/v2/admin) |
| **Mobile Scope Bridge** | Camera capture or GCS demo video streamer (Range/206 & OpenCV fallback) | [https://chakra-os-219670109842.asia-south1.run.app/v2/phone](https://chakra-os-219670109842.asia-south1.run.app/v2/phone) |
| **Doctor Clinical HUD** | Standby gate, sub-30ms L4 CADe overlay, Gemini voice copilot, bilingual discharge, HITL sign-off | [https://chakra-os-219670109842.asia-south1.run.app/v2/doctor](https://chakra-os-219670109842.asia-south1.run.app/v2/doctor) |
| **Real-Time L4 CADe Vision** | Cloud Run NVIDIA L4 GPU worker (24GB VRAM, TensorRT/PyTorch) | [https://chakra-vision-219670109842.asia-southeast1.run.app/warmup](https://chakra-vision-219670109842.asia-southeast1.run.app/warmup) |
| **BigQuery MCP Warehouse** | Read-only clinical DW analytics endpoint (`chakra_clinical_dw.procedures`) | `https://bigquery.googleapis.com/mcp` |
| **Legacy V1 Prototype** | Single-image upload and report prototype | [https://chakra-os-219670109842.asia-south1.run.app/v1](https://chakra-os-219670109842.asia-south1.run.app/v1) |

---

## 2. Technical Architecture Diagram

```mermaid
flowchart TB
    subgraph ClientLayer ["Edge & Client Capture Layer"]
        Phone["📱 Mobile Phone Scope Bridge<br/>(/v2/phone)<br/>Live Camera / GCS Video Streamer"]
        DoctorHUD["🩺 Doctor Clinical HUD<br/>(/v2/doctor)<br/>Standby Gate · Sub-30ms Overlays · Voice Dictation"]
        AdminConsole["⚙️ Admin Console<br/>(/v2/admin)<br/>Model Registry · 6-Digit Code · Direct Inference"]
    end

    subgraph MumbaiRegion ["Google Cloud Region: asia-south1 (Mumbai · MeitY Compliance)"]
        ChakraOS["⚡ chakra-os (Cloud Run)<br/>FastAPI · WebSockets · Range/206 Streaming<br/>Service Account: chakra-review-runtime"]
        BQ["📊 Google BigQuery Warehouse<br/>Dataset: chakra_clinical_dw.procedures<br/>ADR / PDR / BBPS Telemetry · MCP Endpoint"]
    end

    subgraph SingaporeRegion ["Google Cloud Region: asia-southeast1 (NVIDIA L4 Compute)"]
        ChakraVision["🔥 chakra-vision (Cloud Run L4 GPU)<br/>NVIDIA L4 24GB VRAM · Scale-to-Zero<br/>Sub-30ms CADe Bounding Box Detection"]
    end

    subgraph GlobalAI ["Google Vertex AI & Cloud Storage (Global)"]
        GeminiFlash["🧠 Gemini 3.8 Flash<br/>Zero-PHI Voice Note Parsing<br/>Bilingual Clinical Narrative (EN/TA)<br/>ABDM FHIR R4 Bundle"]
        GeminiTTS["🔊 Gemini 3.8 Flash Lite TTS<br/>Empathetic Patient Audio Discharge<br/>English & Natural Tamil (Kore Voice)"]
        GCS["🗄️ Google Cloud Storage<br/>Bucket: girpolypposframesrealcolon-chakra-models<br/>Model Weights · Demo Clips · Evidence JPEGs"]
    end

    %% Connections
    AdminConsole -->|Create Room & Config| ChakraOS
    Phone <-->|WebSocket Depth-1 Relay /ws/v2/{code}/phone| ChakraOS
    DoctorHUD <-->|WebSocket Telemetry /ws/v2/{code}/doctor| ChakraOS
    ChakraOS -->|Asynchronous Frame Inference (3s timeout)| ChakraVision
    ChakraVision -->|Detections & Latency| ChakraOS
    ChakraOS -->|De-identified Voice Transcript| GeminiFlash
    GeminiFlash -->|Structured BBPS & Lesion Dictation| ChakraOS
    ChakraOS -->|Patient Discharge Text| GeminiTTS
    GeminiTTS -->|WAV Audio Bytes| DoctorHUD
    ChakraOS -->|Evidence Keyframes| GCS
    ChakraOS -->|Stream ldpolyp / sun_seg / 1_35.avi| GCS
    DoctorHUD -->|Mandatory HITL Attested Sign-Off| ChakraOS
    ChakraOS -->|Procedure Quality Metrics Insert| BQ
```

---

## 3. Evaluator Rubric Mapping

### 1. Founder Profile & Domain Grounding
- **Endoscopy Dataset Author:** Founded and curated by the author of the `girpolypposframesrealcolon` real-world colonoscopy polyp detection dataset.
- **Deep Clinical Reality Awareness:** Understands clinical ergonomics—endoscopists cannot look away from surgical monitors, cannot touch physical keyboards in sterile suites, and will reject systems that generate false-positive optical malignancy claims.
- **India Health Stack Alignment:** Implements Ayushman Bharat Digital Mission (ABDM) standards, NRCeS FHIR R4 `DiagnosticReportRecord` schemas, and patient de-identification via ABHA pseudonyms.

### 2. Product Potential & Regulatory Navigation
- **De-risked SaMD Strategy:** Bypasses the multi-year Software-as-a-Medical-Device (SaMD) regulatory delay by delivering a Day-1 deployable, Non-SaMD clinical documentation OS (voice copilot, BBPS scoring, bilingual discharge, and quality audits) while isolating real-time white-light CADe as an adjunctive visual aid where pathology is strictly **PENDING_HISTOPATHOLOGY**.
- **Scope-Agnostic Universal Hardware:** Works with existing legacy Olympus, Pentax, and Fujifilm endoscopy towers via any smartphone or tablet bridge without requiring $100,000 capital equipment purchases.

### 3. Market Viability & Unit Economics
- **Sub-Cent Unit Economics:** Google Cloud Run scale-to-zero compute (NVIDIA L4 in `asia-southeast1` + lightweight OS in `asia-south1`) costs **< $0.01 per colonoscopy**, contrasting sharply with Medtronic GI Genius proprietary pricing (~$20,000-$30,000/yr SaaS or ~$40,000-$50,000 CapEx).
- **Enormous Addressable Market:** Over 20 million colonoscopies are performed annually across India and Southeast Asia; >85% of endoscopy centers have zero AI detection tools and rely on error-prone handwritten notes.

### 4. Technical Architecture Excellence
- **Zero-Key Least Privilege IAM:** Runtime executes exclusively under `chakra-review-runtime@girpolypposframesrealcolon.iam.gserviceaccount.com` without hardcoded API keys.
- **Depth-1 Non-Blocking WebSocket Pipeline:** Incoming camera frames are processed asynchronously; any frame arriving while inference is in flight is dropped instantly at depth-1, eliminating WebSocket buffer lag and maintaining a crisp sub-30ms HUD experience.
- **MeitY Sovereign Data Dual-Region Architecture:** Patient data and BigQuery records reside in `asia-south1` (Mumbai) satisfying MeitY data sovereignty, while high-throughput GPU inference routes dynamically to `asia-southeast1` (Singapore) L4 hardware.
- **Universal Video Streaming:** GCS clips stream via HTTP 206 Range requests for `.mp4` and an OpenCV frame-extraction fallback for legacy `.avi` files.
- **Mandatory HITL Attestation Gate:** BigQuery commit is structurally blocked with HTTP 400 unless the clinician explicitly verifies findings and confirms pathology remains pending.

### 5. Deep Use of Google AI & Cloud Stack
- **Vertex AI Gemini 3.8 Flash:** Extracts structured colonoscopy metrics (BBPS right/transverse/left, lesion location, size in mm) from unscripted voice dictation with zero-PHI regex sanitization.
- **Vertex AI Gemini 3.8 Flash Lite TTS:** Synthesizes empathetic patient discharge instructions in natural Tamil and English for clear post-sedation comprehension.
- **Cloud Run NVIDIA L4 GPU:** Sub-30ms edge inference running real-time CADe polyp detection.
- **Google BigQuery Model Context Protocol (MCP):** Live clinical quality data warehouse tracking Adenoma Detection Rate (ADR), Polyp Detection Rate (PDR), and withdrawal time via standardized MCP endpoints.

---

## 4. Pytest Pass Summary (100% Console Verification)

Command executed: `python -m pytest -v tests/test_chakra_v2.py`

```
======================= test session starts =======================
platform win32 -- Python 3.11.9, pytest-9.1.1, pluggy-1.6.0
rootdir: M:\CHAKRA\chakra-buildathon\chakra-os
plugins: anyio-4.14.2
collected 8 items

tests/test_chakra_v2.py::test_room_creation_6_digit_code_and_config PASSED [ 12%]
tests/test_chakra_v2.py::test_standby_gate_no_overlay_before_doctor_start PASSED [ 25%]
tests/test_chakra_v2.py::test_l4_inference_admin_test_frame_and_depth1_dropping PASSED [ 37%]
tests/test_chakra_v2.py::test_gemini_voice_parsing_and_zero_phi_scrubbing PASSED [ 50%]
tests/test_chakra_v2.py::test_hitl_400_block_without_clinician_attestation PASSED [ 62%]
tests/test_chakra_v2.py::test_bigquery_commit_and_analytics PASSED [ 75%]
tests/test_chakra_v2.py::test_gcs_path_traversal_and_xss_security PASSED [ 87%]
tests/test_chakra_v2.py::test_demo_videos_listing_and_range_206_streaming PASSED [100%]

================= 8 passed, 2 warnings in 52.56s ==================
```

---

## 5. Crisp 3-Minute Live Demo Script

### Minute 1: Setup, 6-Digit Pairing & Video Bridge
1. **Open Backend Console:** Navigate to `https://chakra-os-219670109842.asia-south1.run.app/v2/admin`.
2. **Observe System State:** Green status pills indicate Cloud Run NVIDIA L4 is online and BigQuery is ready.
3. **Mint Pairing Code:** Click **"New 6-Digit Code"** (e.g., `313996`). Procedure ID is auto-assigned (`PROC-20261120-313996`).
4. **Open Mobile Scope Bridge:** In a phone or adjacent browser tab, open `/v2/phone?code=313996`.
5. **Select Cloud Demo Video:** Choose `ldpolyp_clip01.mp4` from the dropdown and click **"Stream Clip"**. The status indicator turns green: *"Paired to Room 313996 · Streaming cloud_demo"*.
6. **Notice Doctor HUD State:** The Doctor HUD remains locked in **Standby**. No bounding boxes or AI overlays appear yet (Clinical Safety Gate).

### Minute 2: Standby Gate Unlock, Sub-30ms L4 CADe & Sterile Voice Copilot
1. **Open Doctor HUD:** Open `/v2/doctor?code=313996`.
2. **Review Standby Gate:** Banners show *"Doctor Gate Locked (Standby)"*.
3. **Click Start Procedure:** Click **"▶ Start Procedure"**. Instantly, the video feed unlocks and live bounding boxes highlight candidate polyps with sub-30ms NVIDIA L4 latency.
4. **Sterile Voice Dictation:** Click **"Sample Dictation"** (or use microphone):
   > *"BBPS right 3 transverse 3 left 2, 7mm sessile candidate in cecum, cold snare planned."*
5. **Real-Time Gemini 3.8 Flash Parsing:** Within 1.5 seconds, Gemini scrubs any potential patient identifiers, extracts BBPS score `8/9 (3-3-2)`, updates estimated location to `cecum`, and records the sterile clinical note in the procedure telemetry.

### Minute 3: End Procedure, Gemini Bilingual Discharge, HITL Sign-Off & BigQuery Commit
1. **End Procedure:** Click **"End Procedure & Generate Report"**.
2. **Review Clinical Report Modal:**
   - Preliminary clinical narrative generated by Gemini 3.8 Flash.
   - Surveillance interval calculated (e.g., 7–10 years per USMSTF/ESGE 2020 guidelines).
   - Pathology explicitly flagged as **`PENDING_HISTOPATHOLOGY`**.
3. **Listen to Bilingual Discharge:**
   - Click **"🔊 Speak English Discharge (Gemini TTS)"** — listens to clear post-procedure instructions.
   - Click **"🔊 Speak Tamil Discharge (Gemini TTS)"** — listens to natural Tamil instructions synthesized via `gemini-3.8-flash-lite-tts` (Kore voice).
4. **Verify HITL Attestation Safety Gate:**
   - Attempt to click Sign-Off without checking the attestation box: the button is disabled, protecting against accidental or unverified commits.
   - Check **"Mandatory Physician HITL Attestation"**.
5. **Sign-Off & BigQuery Commit:**
   - Click **"Sign-Off & Commit to BigQuery Warehouse"**.
   - Review live BigQuery receipt in the modal showing zero errors and updated Adenoma Detection Rate (ADR) metrics.
   - Switch back to `/v2/admin` and refresh BigQuery Metrics to observe the live audit update!
