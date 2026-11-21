# CHAKRA GI Clinical OS (V2)

**Scope-Agnostic Endoscopy Reporting & Quality Audit OS with Adjunctive Real-Time Polyp CADe**  
*Built for the Google Cloud & Vertex AI Buildathon on Project `girpolypposframesrealcolon`*

[![Pytest Status](https://img.shields.io/badge/pytest-100%25%20passed-success)](tests/test_chakra_v2.py)
[![Cloud Run Asia-South1](https://img.shields.io/badge/Cloud%20Run-asia--south1%20(Mumbai)-blue)](https://chakra-os-219670109842.asia-south1.run.app/v2/admin)
[![Cloud Run L4 GPU](https://img.shields.io/badge/NVIDIA%20L4-asia--southeast1-green)](https://chakra-vision-219670109842.asia-southeast1.run.app/warmup)
[![Vertex AI Gemini](https://img.shields.io/badge/Vertex%20AI-Gemini%203.8%20Flash-orange)](https://cloud.google.com/vertex-ai)
[![ABDM FHIR R4](https://img.shields.io/badge/Standards-ABDM%20FHIR%20R4-purple)](https://nrces.in)

---

## 🌟 Live Cloud Deployment

- ⚙️ **Backend Console (Setup, 6-Digit Pairing & Analytics):**  
  [https://chakra-os-219670109842.asia-south1.run.app/v2/admin](https://chakra-os-219670109842.asia-south1.run.app/v2/admin)
- 📱 **Mobile Scope Bridge (Phone Camera / GCS Video Streamer):**  
  [https://chakra-os-219670109842.asia-south1.run.app/v2/phone](https://chakra-os-219670109842.asia-south1.run.app/v2/phone)
- 🩺 **Doctor Clinical HUD (Standby Gate, Live L4 Overlay, Voice Dictation, Sign-Off):**  
  [https://chakra-os-219670109842.asia-south1.run.app/v2/doctor](https://chakra-os-219670109842.asia-south1.run.app/v2/doctor)
- 🚀 **NVIDIA L4 Real-Time Vision Backend:**  
  [https://chakra-vision-219670109842.asia-southeast1.run.app/warmup](https://chakra-vision-219670109842.asia-southeast1.run.app/warmup)
- 📊 **Google BigQuery Quality & ADR Warehouse (MCP):**  
  `https://bigquery.googleapis.com/mcp` (Table: `girpolypposframesrealcolon.chakra_clinical_dw.procedures`)
- 🧪 **Legacy V1 Single-Image Prototype:**  
  [https://chakra-os-219670109842.asia-south1.run.app/v1](https://chakra-os-219670109842.asia-south1.run.app/v1)

*Detailed buildathon documentation, rubric mapping, and live demo script are in [SUBMISSION_PACK.md](SUBMISSION_PACK.md).*

---

## 💡 What is CHAKRA V2?

Colonoscopy is the global gold standard for colorectal cancer prevention, but conventional clinical GI suites face three critical bottlenecks:
1. **Regulatory SaMD Deadlock:** Complex AI diagnostic models claim optical biopsy or tissue classification, triggering years of Class C/D SaMD delays.
2. **Exorbitant Capital Costs:** Proprietary AI systems (e.g. Medtronic GI Genius) cost **~$20,000-$30,000/yr SaaS (~$40,000-$50,000 CapEx)**, locking out 85%+ of community hospitals in India and Southeast Asia.
3. **Sterile Workflow Friction:** Endoscopists cannot touch physical keyboards during procedures, resulting in delayed, inconsistent, handwritten reporting and low Bowel Preparation (BBPS) / Adenoma Detection Rate (ADR) audit adherence.

### The CHAKRA Solution:
- **Day-1 Non-SaMD Clinical OS:** Sterile voice copilot powered by **Vertex AI Gemini 3.8 Flash** with zero-PHI sanitization, automatic Boston Bowel Preparation Scale (BBPS) evaluation, surveillance interval guidance (USMSTF/ESGE 2020), and NRCeS ABDM FHIR R4 structured bundles.
- **Isolated White-Light CADe Visual Aid:** Real-time polyp candidate detection bounding boxes running on **Google Cloud Run NVIDIA L4 GPU** at sub-30ms latency, strictly flagged as **`PENDING_HISTOPATHOLOGY`** without optical malignancy claims.
- **Bilingual Post-Procedure Discharge:** Empathetic voice synthesis in natural **Tamil and English** using **Gemini 3.8 Flash Lite TTS** (Kore voice), ensuring patients and caregivers understand post-sedation instructions.
- **Mandatory HITL Attestation Gate:** BigQuery clinical warehouse commit is structurally blocked unless the clinician verifies accepted keyframes and attests findings.

---

## 🏛️ System Architecture

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

## 🛠️ Key Capabilities & Features

### 1. HTTP 206 Range Streaming & OpenCV Fallback
- `GET /api/v2/demo-videos`: Lists demo clips staged in `gs://girpolypposframesrealcolon-chakra-models/demo_videos/`.
- `GET /api/v2/demo-videos/{name}`: Implements RFC 7233 partial content byte-range streaming for `.mp4` (`ldpolyp_clip01.mp4`, `sun_seg_seq01.mp4`).
- `GET /api/v2/demo-videos/{name}/frame`: Dynamic frame extraction using OpenCV (`cv2.VideoCapture`) for legacy `.avi` clips (`1_35.avi`) where browsers lack native container decoders.
- **Strict Path-Traversal Security:** Blocks directory traversal, null bytes, backslashes, and XSS attempts with HTTP 400/404.

### 2. Depth-1 Non-Blocking WebSocket Pipeline
- `/ws/v2/{code}/{role}`: Bi-directional WebSocket relay supporting `admin`, `phone`, and `doctor` roles.
- **Depth-1 Non-Blocking Frame Dropping:** Camera frame processing is dispatched asynchronously with a 3.0s timeout. If inference is in-flight, incoming frames are dropped immediately at the socket level without buffering, guaranteeing zero queue lag and crisp real-time HUD latency.
- **Standby Gate:** Live video and AI bounding boxes remain locked in standby until the endoscopist explicitly clicks "Start Procedure".

### 3. Voice Dictation & Zero-PHI Scrubbing
- **Automatic De-identification:** Regex sanitizers strip 12-digit Indian National IDs (Aadhaar) and 10-digit phone numbers before sending transcripts to Vertex AI.
- **Structured Clinical Extraction:** `gemini-3.8-flash` populates segment-wise BBPS scores, polyp anatomical location, and maximum size in millimeters.

### 4. Mandatory Physician HITL Attestation Gate
- Before procedural records and ADR metrics can be committed to the Google BigQuery clinical warehouse, the physician must explicitly attest the preliminary report.
- Unattested sign-off attempts return **HTTP 400 Bad Request**.

---

## 🧪 Console Test Suite

The test suite thoroughly exercises clinical workflow gates, security barriers, streaming mechanics, and data integrity:

```bash
python -m pytest -v tests/test_chakra_v2.py
```

### Test Coverage Breakdown:
1. `test_room_creation_6_digit_code_and_config`: Verifies 6-digit numeric room codes and configuration updates.
2. `test_standby_gate_no_overlay_before_doctor_start`: Enforces that no video overlay is emitted prior to clinician start.
3. `test_l4_inference_admin_test_frame_and_depth1_dropping`: Verifies L4 detection response and depth-1 frame dropping.
4. `test_gemini_voice_parsing_and_zero_phi_scrubbing`: Tests regex scrubbing of patient identifiers and structured dictation extraction.
5. `test_hitl_400_block_without_clinician_attestation`: Confirms HTTP 400 rejection on unattested sign-off attempts.
6. `test_bigquery_commit_and_analytics`: Confirms BigQuery insertion, MCP endpoint receipt, and analytics schema.
7. `test_gcs_path_traversal_and_xss_security`: Verifies that path traversal and injection payloads are blocked.
8. `test_demo_videos_listing_and_range_206_streaming`: Tests HTTP 206 Partial Content Range streaming and OpenCV frame fallback.

---

## 🚀 Local Development Quickstart

```bash
# 1. Clone repository
git clone https://github.com/Gokzz-glitch/chakra-os.git
cd chakra-os

# 2. Install dependencies
pip install -r requirements.txt

# 3. Set environment variables (or rely on Cloud defaults)
export GOOGLE_CLOUD_PROJECT="girpolypposframesrealcolon"
export VISION_URL="https://chakra-vision-219670109842.asia-southeast1.run.app"
export VERTEX_LOCATION="global"
export GEMINI_MODEL="gemini-3.8-flash"
export TTS_MODEL="gemini-3.8-flash-lite-tts"
export GCS_BUCKET="girpolypposframesrealcolon-chakra-models"

# 4. Run test suite
python -m pytest -v tests/test_chakra_v2.py

# 5. Start local server
uvicorn main:app --host 0.0.0.0 --port 8080 --reload
```

---

## 📋 Evaluation Rubric Alignment

| Rubric Criteria | CHAKRA Implementation |
| :--- | :--- |
| **Founder Profile** | **Gokul Rajasekar** (Founder & Lead Architect); Co-Founders: **Varsha** (Clinical Ops), **Girupa** (AI Systems & `girpolypposframesrealcolon` dataset author), **Jayasri** (Compliance & ABDM FHIR R4); deep clinical GI workflow grounding; India MeitY data sovereignty integration. |
| **Product Potential** | Day-1 deployable Non-SaMD documentation OS de-risking regulatory pathways while isolating white-light visual CADe; scope-agnostic universal camera bridge. |
| **Market Viability** | Sub-cent unit economics (<$0.01/procedure) on Cloud Run scale-to-zero vs ~$20,000-$30,000/yr SaaS (~$40,000-$50,000 CapEx) proprietary hardware; addressable market of 20M+ colonoscopies in India and SE Asia. |
| **Technical Architecture** | Zero-key least-privilege IAM runtime; dual-region MeitY compliance (`asia-south1`) + NVIDIA L4 GPU (`asia-southeast1`); depth-1 non-blocking WebSocket pipeline; Range/206 streaming with OpenCV fallback. |
| **Use of Google AI** | Vertex AI Gemini 3.8 Flash zero-PHI voice parsing; Gemini 3.8 Flash Lite TTS bilingual audio discharge (EN/TA); Cloud Run NVIDIA L4 CADe; BigQuery MCP quality warehouse. |

---

## 📜 License & Compliance
- **Compliance:** Designed for CDSCO Class B scope guidelines (adjunctive visual CADe aid only; optical pathology disabled; final diagnosis strictly contingent on histopathology).
- **ABDM Standards:** NRCeS FHIR R4 `DiagnosticReportRecord` profile compliant.
