# Security and clinical safety verification

This branch adds controls for the CHAKRA research prototype. Each row links a failure mode to executable evidence. Clinical validation, an approved risk-management file and release authorization require separate review.

| Failure mode | Implemented control | Regression evidence |
| --- | --- | --- |
| A user reads or changes another hospital's records | Verify IAP identity, bind a grant to a deployment tenant, enforce roles on HTTP and WebSocket, filter records and queries by tenant | `tests/test_clinical_access.py`, `tests/test_patient_history_workflow.py`, `tests/test_hardening.py` |
| Recorded text or generated content executes in a browser | Render values as text, serve scripts and QR locally, enforce CSP and prohibit clinical page caching | `tests/test_hardening.py`, `tests/browser_clinical_smoke.py` |
| Pairing attempts, large frames or repeated requests consume clinical capacity | Require exact browser origins, limit requests by verified identity, expire pairing codes, cap JPEG/PNG frames at 5 MiB | `tests/test_hardening.py` |
| A clinician sees a false negative or signs unmeasured values | Surface inference failure, require measured values, preserve missing timer status and gate sign-off on review and attestation | `tests/test_hardening.py`, `tests/test_chakra_v2.py`, `tests/test_exhaustive_features.py` |
| A pathology correction erases the original result | Create generation-protected original and addendum objects. Read back persisted entries before reporting success. Retried identical submissions are idempotent | `tests/test_patient_history_workflow.py`, `tests/test_hardening.py` |
| Logs expose identifiers or a worker loads substituted weights | Emit keyed audit references, scrub recognized text identifiers, verify the checkpoint digest before model loading and restrict segmentation deserialization | `tests/test_hardening.py` |

## Deployment configuration

Provision one tenant per service deployment. Set `ENV=production`, `CHAKRA_TENANT_ID`, `CHAKRA_REGION`, `GOOGLE_CLOUD_PROJECT`, `VISION_URL`, `GCS_BUCKET`, `CHAKRA_ACCESS_BUCKET` and `CHAKRA_PATHOLOGY_BUCKET`. Set `IAP_AUDIENCE` to the protected service audience or set `PROJECT_NUMBER` and use the Cloud Run service identity configuration. Set `ALLOWED_HOSTS` to the exact HTTPS browser origins used by clinicians and operators. Supply a stable `CHAKRA_AUDIT_HMAC_KEY` of at least 32 random bytes through Secret Manager. Keep IAP and service-to-service IAM enabled.

Give the clinical runtime read access to the tenant's grant objects and read/create access to its pathology journal. Use a separate administrative identity for account management. Deny the runtime deletion and replacement of pathology entries. The shared quota window prefix in the media bucket requires read and conditional write access. Keep tenant media, grants and pathology objects private. An existing deployment needs these settings and IAM permissions before rollout.

## Verification scope

Run `python -m pytest -v` for application, security and safety tests. With Chrome and Playwright installed, run `python -m pytest -v tests/browser_clinical_smoke.py` for browser enforcement and role-specific interactions. Both use synthetic fixtures and isolated cloud-service doubles.

`sbom.json` inventories the pinned application Python dependencies and vendored QR library. The GPU base image and operating-system packages require image-level inventory. The trusted model digests are in `evaluation/checkpoint_hashes.json`; changing a checkpoint requires reviewing its provenance before updating the allowlist.

Room state and live WebSocket connections are process-local. Multi-instance room routing and recovery after a restart need deployment testing. Redaction recognizes the tested identifier formats and cannot establish that arbitrary free text is anonymous. Verify console and infrastructure log retention separately from the application's structured audit events.
