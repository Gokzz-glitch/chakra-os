# CHAKRA GI Clinical OS (V2) — Pre-Launch Security & Verification Report

> Historical pre-hardening report. For current controls, configuration and verification scope, see [Security and clinical safety verification](SECURITY_HARDENING.md).

**Date:** November 2026  
**Target Environment:** Google Cloud Run (`asia-south1` / `asia-southeast1`)  
**Project:** `girpolypposframesrealcolon`  
**Test Suite Coverage:** 52 / 52 Automated Tests Passing (100%)

---

## 1. Executive Summary

This report documents the security hardening, prompt injection defense, and UI clinical de-vibecoding applied to CHAKRA V2 prior to public buildathon evaluation. All public demo and clinician workflows remain 100% functional without requiring physician login, while securing all compute, AI, and storage interfaces against adversarial abuse, credential exposure, cross-tenant data leakage, and unmetered billing drains.

---

## 2. Automated Security Verification (52 Tests Passing)

| Test Module | Coverage Area | Status |
| :--- | :--- | :--- |
| `tests/test_chakra_v2.py` (15 tests) | Security headers, `/docs` prod gate, rate limiting (429), oversized inputs (400/422), zero-PHI scrubbing, HITL gates, FL manifest export | **PASSED (100%)** |
| `tests/test_patient_history_workflow.py` (4 tests) | Cross-hospital tenant isolation (`X-Hospital-ID`), delayed pathology reconciliation, audit preservation | **PASSED (100%)** |
| `tests/test_hybrid_5videos.py` (12 tests) | Video range streaming (HTTP 206), OpenCV frame extraction, audio discharge synthesis, BigQuery warehouse telemetry | **PASSED (100%)** |
| `tests/test_exhaustive_features.py` (21 tests) | End-to-end clinical workflow, model registry, depth-1 WebSocket standby gate, non-blocking L4 CADe | **PASSED (100%)** |

---

## 3. Implemented Security Controls

### A. Environment-Gated API Documentation
- **Control:** Interactive Swagger UI (`/docs`), ReDoc (`/redoc`), and raw OpenAPI schema (`/openapi.json`) are automatically disabled (returning HTTP 404) when running in production mode (`ENV=production` or `K_SERVICE` set).
- **Benefit:** Prevents external reconnaissance of schema models and parameter spaces.

### B. Global Opaque Exception Handler
- **Control:** Added FastAPI application-level exception handler that catches unhandled 500 exceptions, generates a pseudorandom `request_id`, and returns a clean error payload.
- **Benefit:** Completely eliminates Python stack traces, internal file paths, and environment leaks to external callers.

### C. Enterprise HTTP Security Headers
Every HTTP and WebSocket upgrade response injects modern defensive headers:
- `X-Content-Type-Options: nosniff` (mitigates MIME-type confusion attacks)
- `X-Frame-Options: DENY` (prevents clickjacking and unauthorized iframe embedding)
- `Referrer-Policy: strict-origin-when-cross-origin` (prevents referrer token leakage)
- `Strict-Transport-Security: max-age=63072000; includeSubDomains` (enforces strict HTTPS)

### D. Strict CORS Origin Whitelisting
- **Control:** Replaced permissive wildcard CORS with an explicit whitelist:
  - `https://chakra-os-219670109842.asia-south1.run.app`
  - `https://chakra-os-m7s24zsk6q-el.a.run.app`
  - `https://chakra-vision-219670109842.asia-southeast1.run.app`
  - `http://localhost:8080`, `http://127.0.0.1:8080` (local development)
- **Benefit:** Prohibits credentialed cross-origin requests from arbitrary third-party web domains.

### E. Per-IP Sliding-Window Rate Limiting
- **Control:** In-memory sliding-window limiter enforcing a maximum of **30 requests per minute** on paid AI and GPU endpoints:
  - `/api/v2/voice-parse` & `/api/v2/rooms/{code}/voice-note` (Vertex AI Gemini 3.8 Flash)
  - `/api/v2/report` & `/api/v2/rooms/{code}/end-report` (Gemini Narrative + GCS Upload)
  - `/api/v2/tts` & `/api/v2/rooms/{code}/tts` (Gemini Flash Lite TTS)
  - `/api/v2/admin/test-frame` & `/api/v2/rooms/{code}/admin-test-frame` (NVIDIA L4 GPU)
- **Behavior:** Triggers HTTP 429 with `Retry-After: 60` and clean JSON response when exceeded.

### F. Prompt Injection & Input Length Hardening
- **Control:** 
  1. Wrapped clinician voice dictations in `<transcript>...</transcript>` delimiters with an explicit security mandate instructing Gemini to treat enclosed text as passive data and ignore embedded instructions or role-reversal attempts.
  2. Enforced a hard character ceiling of **2,000 characters** via Pydantic model validation (`Field(..., max_length=2000)`) and route handlers, immediately rejecting oversized payloads with HTTP 400/422.

### G. Zero-PHI Sanitization (India DPDP Act 2023 & HIPAA)
- **Control:** Client-side and backend regex scrubbing pipeline redacting 12-digit Indian National IDs (Aadhaar), 10-digit mobile numbers, ABHA `@abdm` addresses, hospital MRNs/UHIDs, and explicit patient name patterns prior to Vertex AI ingestion or BigQuery persistence.

### H. Multi-Tenant Hospital Boundary Enforcement
- **Control:** Enforced `X-Hospital-ID` header checks on patient history and pathology reconciliation registries. Cross-hospital access attempts return HTTP 403 Forbidden with zero data leakage.

---

## 4. UI De-Vibecoding & Clinical Polish

1. **Complete Removal of Emojis:** Replaced all informal emojis across `admin.html`, `doctor.html`, and `phone.html` with clean monochrome inline SVG icons (sun/moon theme toggles, mobile scope, microphone, speaker, download, check, and close).
2. **Crisp 8px-10px Clinical Radii:** Replaced oversized 100px rounded pill buttons with crisp 8px clinical border-radii aligned with enterprise hospital EHR design standards (Epic, Cerner, Google Cloud Console).
3. **CSS Shimmer Skeleton Loaders:** Added lightweight `@keyframes shimmer` animated skeleton cards to BigQuery Analytics and Patient History panels while fetching asynchronous cloud responses.
4. **Clinical Footer & Legal Modals:** Added an accessible clinical footer to all interfaces featuring modal dialogues for:
   - **Privacy & DPDP Notice:** Detailing client-side scrubbing, MeitY sovereignty in `asia-south1`, and zero-PHI FL manifests.
   - **Terms of Use (Non-SaMD Prototype):** Highlighting CDSCO Class B scope positioning, non-diagnostic CADe visual aid isolation, and histopathology mandates.

---

## 5. Manual GCP Dashboard Action Items (Post-Deployment)

To guarantee cloud cost control and repository hygiene beyond code-level measures:

1. **Cloud Billing Budget & Alerts:**
   - Navigate to **Google Cloud Console > Billing > Budgets & alerts**.
   - Create a budget for project `girpolypposframesrealcolon` (e.g. $50 threshold).
   - Configure alert triggers at 50%, 90%, and 100% with automated pub/sub notifications to project administrators.

2. **GitHub Secret Scanning & Push Protection:**
   - Navigate to GitHub repository **Settings > Code security and analysis**.
   - Ensure **Secret scanning** and **Push protection** are active to prevent accidental credential commits.
   - Confirm that all runtime calls continue to operate under Google Cloud Workload Identity / Service Account IAM (`chakra-review-runtime@girpolypposframesrealcolon.iam.gserviceaccount.com`) without hardcoded service account JSON keys.
