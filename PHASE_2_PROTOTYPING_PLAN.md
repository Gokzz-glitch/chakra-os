# CHAKRA GI Clinical OS (V2) - Phase 2 Prototyping & Clinical Workflow Design

## 1. Product Positioning & Workflow

**Problem Statement:** Endoscopists and administrators lose critical time and diagnostic context attempting to reconcile returning patients’ historical endoscopic findings with delayed pathology reports across fragmented hospital systems.

**Solution Statement:** CHAKRA V2 unites real-time edge AI detection with an interactive, verifiable patient history that automatically reconciles pending pathology against captured endoscopic evidence.

**Elevator Pitch (100 words):** 
In a busy endoscopy suite, time is everything. Today, when a patient returns, doctors waste critical minutes digging through fragmented systems trying to match old images with delayed pathology reports. CHAKRA V2 solves this by building the workflow around the clinical journey. We capture real-time AI detections as verifiable episodes. When the pathology report finally arrives, CHAKRA instantly reconciles it with the exact frame from the procedure, preserving the doctor's original review. By uniting Google Cloud Run, BigQuery analytics, and Gemini's zero-PHI summarization, we give the endoscopist instant context, the admin clear audits, and the patient safer, faster care.

## 2. Asset Audit & Deployed Baseline

- **CHAKRA Review Studio:** Deployed in `girpolypposframesrealcolon` (Revision: `chakra-review-studio-00008-vpq`, Region: `asia-south1`).
  * *Audit Note:* Access control initially restricted to IAM service account (`chakra-browser-view`). Updated IAM to allow `allUsers` for public/mentor access, resolving the HTTP 500 sign-in error for the Cloud Demo.
- **Models & Revisions:** The live inference edge node leverages Cloud Run NVIDIA L4 (asia-southeast1). Model catalog includes YOLOViT-YOLO (baseline real-time CADe), PVT-PraNet, AdaBN-ChakraNet, SEPNet, and RF-DETR-S.
- **Baseline Model:** YOLOViT-YOLO (`weights.pt`). Predicts real-time bounding boxes (CADe). Detections are tracked and aggregated over time intervals into a single "episode" to prevent false-multiple logs. 
- *Next Verification:* Ensure that only the highest-confidence frame per episode is retained for review.

## 3. Mentor Cloud Demo Usability

- **Access:** Unauthenticated invoker access granted to `https://chakra-review-studio-m7s24zsk6q-el.a.run.app` ensuring mentors can access it without a Google account login loop. 
- **Session Handling:** Stateless backend execution using Cloud Run and BigQuery MCP.
- **Credit Use:** Inference defaults to Cloud Run L4 Scale-to-Zero (`min-instances=0`), avoiding idle GPU burn. The web dashboard and state tracking use CPU-only Cloud Run instances (`< $0.01` per procedure).

## 4. Detection & Segmentation Evaluation Plan

- **Baseline Metrics to Track:** Startup time, frames per second (FPS), median latency (ms), 95th-percentile latency (ms).
- **Episode Grouping Strategy:** Bounding boxes appearing within a 3-5 second temporal window at the same relative spatial location are grouped into a single "Episode". If an object leaves the FOV and returns, it triggers a new episode unless ReID embeddings (future) bridge the gap.
- **Condition Testing:** Establish discrete testing brackets for: Insertion, Withdrawal, Washing/Flushing, Blur/Glare, Instrument Obstruction.
- **Segmentation Criteria:** Only evaluate SAM 2 or dense mask models if the current bounding box boundary precision negatively impacts clinical decision-making or polyp sizing.

## 5. Patient History & Verification Schema

**Minimum Viable Schema:**
- `hospital_id`: String (e.g., HOSP-CHENNAI-01)
- `patient_anonymized_id`: String (ABHA pseudonym)
- `encounter_id`: String
- `finding_id`: String (e.g., FND-01)
- `timestamp`: UTC ISO8601
- `evidence_gcs_uri`: String
- `location_estimated`: String
- `size_estimated_mm`: Float
- `morphology`: String
- `physician_decision`: Enum (ACCEPTED, DISMISSED)
- `pathology_status`: Enum (PENDING, SIGNED)
- `signed_result`: String (Pathology integration)

**Access Control:** Read/Write by attending physician. Read-only by admin staff. Zero-PHI enforced on all LLM summaries.

**Gemini Drafting Rules:** 
1. Use only approved facts. 
2. Retain source links to the evidence frame.
3. Explicitly flag missing pathology. 
4. Output is strictly a "Draft" pending `hitl_attested=True`.

## 6. Google Technology Alignment

- **Cloud Run (asia-south1):** API hosting, CPU web serving, secure WebSocket relay.
- **Cloud Run L4 GPU (asia-southeast1):** Real-time TensorRT/PyTorch CADe inference.
- **Cloud Storage (GCS):** Durable evidence storage, zero-disk byte-range streaming for demo videos.
- **Vertex AI (Gemini 3.8 Flash & TTS):** Zero-PHI dictation, clinical summary generation, bilingual patient discharge.
- **BigQuery MCP:** Immutable, append-only quality data warehouse.

## 7. Specialist-Model Research Plan

- **Baseline:** YOLOViT-YOLO.
- **Target Failure:** High false-positive rate during bowel washing/flushing phases.
- **Proposed Experiment (Mixture-of-Experts/Routing):** Route frames identified as "washing/fluid" to a specialized suppression adapter. 
- **Success Metric:** > 40% reduction in false alerts per minute without decreasing the Adenoma Detection Rate (ADR).
- **Stopping Rule:** If L4 latency exceeds 35ms (drops below 28 FPS), halt the experiment to preserve real-time HUD rendering.

## 8. Market Viability & Centre Pitch

**Target Buyer:** Independent Endoscopy Centre (India).

**Interview Hypothesis - Endoscopist:**
*"Walk me through the last time a returning patient’s pathology report was difficult to reconcile. Who searched for it, how long did it take, and what happened next?"*

**Interview Hypothesis - Administrator:**
*"How do you currently track Adenoma Detection Rate across different physicians? If a system could automate this without changing the surgical workflow, what is the maximum CapEx or SaaS subscription your board would approve for a one-room pilot?"*
