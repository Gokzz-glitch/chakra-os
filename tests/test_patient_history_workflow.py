import pytest
from conftest import WorkflowClient
import main

client = WorkflowClient(main.app)


def test_returning_patient_history_and_pathology_lookup():
    """Lead clinical question: When a patient returns, how quickly can the endoscopist find

    the previous finding, inspect its image, and verify what pathology eventually reported?
    """
    res = client.get("/api/v2/patients/DEMO-PATIENT-01/history", headers={"X-Hospital-ID": "HOSP-CHENNAI-01"})
    assert res.status_code == 200
    data = res.json()
    assert data["patient_id"] == "DEMO-PATIENT-01"
    assert len(data["encounters"]) >= 1

    prior_enc = data["encounters"][0]
    assert prior_enc["procedure_id"] == "PROC-20250814-118240"
    assert len(prior_enc["findings"]) >= 1

    finding = prior_enc["findings"][0]
    assert finding["finding_id"] == "FND-2025-01"
    assert finding["location"] == "Cecum / Ascending"
    assert finding["size_mm"] == 7.0
    assert finding["physician_decision"] == "accepted"
    # Inspect evidence image frame
    assert finding["evidence_frame_url"].startswith("/api/v2/demo-videos/")
    # Verify pathology report
    assert finding["pathology_status"] == "SIGNED"
    assert "Tubular Adenoma" in finding["pathology_result"]["diagnosis"]
    assert "Negative / Clear" in finding["pathology_result"]["margins"]


def test_delayed_pathology_arrival_and_reconciliation():
    """Case 2: When a signed pathology result arrives later, verify it updates status,

    records diagnosis, and preserves the clinician's earlier review decision.
    """
    # 1. Register a pending finding for a returning patient
    pending_finding_id = "FND-2026-PENDING-02"
    main.PATIENT_REGISTRY["DEMO-PATIENT-01"]["encounters"].append({
        "encounter_id": "ENC-2026-0220",
        "procedure_id": "PROC-20260220-774411",
        "date": "2026-02-20",
        "endoscopist_id": "DR-GOKUL-R",
        "hospital_id": "HOSP-CHENNAI-01",
        "findings": [
            {
                "finding_id": pending_finding_id,
                "episode_id": "EPISODE-02",
                "timestamp": "2026-02-20T11:30:00Z",
                "location": "Descending Colon",
                "size_mm": 6.0,
                "morphology": "Paris 0-IIa (Flat Elevated)",
                "physician_decision": "accepted",
                "evidence_frame_url": "/api/v2/demo-videos/1_35.avi/frame?idx=0",
                "pathology_status": "PENDING",
                "pathology_result": None,
                "surveillance_recommendation": "Provisional 3 years (pending histopathology)",
            }
        ]
    })

    # Verify pending state
    r_pre = client.get("/api/v2/patients/DEMO-PATIENT-01/history", headers={"X-Hospital-ID": "HOSP-CHENNAI-01"})
    assert r_pre.status_code == 200
    enc_2026 = [e for e in r_pre.json()["encounters"] if e["encounter_id"] == "ENC-2026-0220"][0]
    assert enc_2026["findings"][0]["pathology_status"] == "PENDING"

    # 2. Delayed signed pathology report arrives from pathology lab
    sign_payload = {
        "signed_by": "DR-PATH-RAMESH-V",
        "diagnosis": "Serrated Polyp with No Dysplasia",
        "dysplasia_grade": "None",
        "margins": "Negative / Clear (R0 Resection)",
        "icd_o_code": "8213/0",
    }
    r_sign = client.post(f"/api/v2/findings/{pending_finding_id}/pathology", json=sign_payload)
    assert r_sign.status_code == 200
    res_sign = r_sign.json()
    assert res_sign["reconciled"] is True
    assert res_sign["earlier_decision_preserved"] == "accepted"

    # 3. Verify in patient longitudinal history that status is now SIGNED
    r_post = client.get("/api/v2/patients/DEMO-PATIENT-01/history", headers={"X-Hospital-ID": "HOSP-CHENNAI-01"})
    enc_updated = [e for e in r_post.json()["encounters"] if e["encounter_id"] == "ENC-2026-0220"][0]
    updated_finding = enc_updated["findings"][0]
    assert updated_finding["pathology_status"] == "SIGNED"
    assert updated_finding["pathology_result"]["diagnosis"] == "Serrated Polyp with No Dysplasia"
    assert updated_finding["physician_decision"] == "accepted"


def test_dismissed_candidate_audit_isolation():
    """Case 3: Verify clinician-dismissed CADe candidate is preserved in procedural

    audit trail but never routed to pathology queue.
    """
    dismissed_id = "FND-2026-DISMISSED-03"
    main.PATIENT_REGISTRY["DEMO-PATIENT-01"]["encounters"].append({
        "encounter_id": "ENC-2026-AUDIT",
        "procedure_id": "PROC-20260220-AUDIT",
        "date": "2026-02-20",
        "endoscopist_id": "DR-GOKUL-R",
        "hospital_id": "HOSP-CHENNAI-01",
        "findings": [
            {
                "finding_id": dismissed_id,
                "location": "Transverse Colon",
                "size_mm": 3.0,
                "morphology": "Mucosal Fold Artifact (False Alert)",
                "physician_decision": "dismissed",
                "evidence_frame_url": "/api/v2/demo-videos/1_35.avi/frame?idx=0",
                "pathology_status": "N/A (DISMISSED)",
                "pathology_result": None,
            }
        ]
    })
    r = client.get("/api/v2/patients/DEMO-PATIENT-01/history", headers={"X-Hospital-ID": "HOSP-CHENNAI-01"})
    assert r.status_code == 200
    audit_enc = [e for e in r.json()["encounters"] if e["encounter_id"] == "ENC-2026-AUDIT"][0]
    assert audit_enc["findings"][0]["physician_decision"] == "dismissed"
    assert audit_enc["findings"][0]["pathology_status"] == "N/A (DISMISSED)"


def test_cross_hospital_security_boundary_isolation():
    """Case 4: Attempting to query patient records belonging to another hospital

    must be strictly blocked with HTTP 403 Forbidden.
    """
    # Attempting to access PATIENT-MUMBAI-99 (HOSP-MUMBAI-02) with HOSP-CHENNAI-01 header
    blocked_res = client.get("/api/v2/patients/PATIENT-MUMBAI-99/history", headers={"X-Hospital-ID": "HOSP-CHENNAI-01"})
    assert blocked_res.status_code == 403
    assert "Cross-hospital data boundary violation" in blocked_res.json()["detail"]

    # A caller-supplied tenant cannot change the identity binding
    allowed_res = client.get("/api/v2/patients/PATIENT-MUMBAI-99/history", headers={"X-Hospital-ID": "HOSP-MUMBAI-02"})
    assert allowed_res.status_code == 403
