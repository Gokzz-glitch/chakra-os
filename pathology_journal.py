"""Tenant-scoped immutable pathology entries. A generation-zero write cannot replace an object."""

import copy
import hashlib
import json

from fastapi import HTTPException
from google.api_core.exceptions import PreconditionFailed
from google.cloud import storage

from security_settings import PROJECT, TENANT, setting

BUCKET = setting("CHAKRA_PATHOLOGY_BUCKET", "development-pathology")


def bucket():
    return storage.Client(project=PROJECT).bucket(BUCKET)


def digest(value):
    return hashlib.sha256(value.encode()).hexdigest()


def prefix(patient_id):
    return f"pathology/{digest(TENANT)}/{digest(patient_id)}/"


def entries(patient):
    """Rebuild the clinical view using immutable originals and ordered amendments."""
    patient = copy.deepcopy(patient)
    findings = {
        f["finding_id"]: f
        for encounter in patient["encounters"]
        for f in encounter["findings"]
    }
    try:
        objects = bucket().list_blobs(prefix=prefix(patient["patient_id"]))
        for obj in objects:
            data = json.loads(
                obj.download_as_bytes(if_generation_match=obj.generation, timeout=10)
            )
            finding = findings.get(data["finding"])
            if finding is None:
                continue
            if (
                data["kind"] == "initial"
                and finding.get("pathology_status") != "SIGNED"
            ):
                finding.update(
                    pathology_result=data["entry"],
                    pathology_status="SIGNED",
                    surveillance_recommendation=data["recommendation"],
                )
            elif data["kind"] == "addendum":
                finding.setdefault("pathology_addenda", []).append(data["entry"])
        for finding in findings.values():
            if "pathology_addenda" in finding:
                finding["pathology_addenda"].sort(key=lambda row: row["signed_at"])
    except Exception as exc:
        raise HTTPException(503, "Pathology history unavailable") from exc
    return patient


def append(patient, finding, entry, recommendation):
    target = prefix(patient["patient_id"]) + digest(finding["finding_id"]) + "/"
    signature = digest(
        json.dumps({k: v for k, v in entry.items() if k != "signed_at"}, sort_keys=True)
    )
    event = {
        "finding": finding["finding_id"],
        "entry": entry,
        "recommendation": recommendation,
    }
    try:
        store = bucket()
        if finding.get("pathology_status") != "SIGNED":
            original = store.blob(target + "initial.json")
            try:
                original.upload_from_string(
                    json.dumps(dict(event, kind="initial")),
                    content_type="application/json",
                    if_generation_match=0,
                    timeout=10,
                )
                return
            except PreconditionFailed:
                previous = json.loads(original.download_as_bytes(timeout=10))["entry"]
                if all(
                    previous.get(k) == v for k, v in entry.items() if k != "signed_at"
                ):
                    return
        amendment = store.blob(target + "addenda/" + signature + ".json")
        try:
            amendment.upload_from_string(
                json.dumps(dict(event, kind="addendum")),
                content_type="application/json",
                if_generation_match=0,
                timeout=10,
            )
        except PreconditionFailed:
            pass  # The same signer and content have already been journaled.
    except Exception as exc:
        raise HTTPException(503, "Pathology entry could not be saved") from exc
