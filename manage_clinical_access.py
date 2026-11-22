"""Manage one account in CHAKRA's synthetic Chennai hospital, using operator Google credentials."""
import argparse
import hashlib
import json
import os
from pathlib import Path
import re
import shutil
import subprocess

from google.api_core.exceptions import NotFound
from google.cloud import storage

PROJECT = "girpolypposframesrealcolon"
BUCKET = PROJECT + "-chakra-access"


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    actions = parser.add_subparsers(dest="action", required=True)
    grant = actions.add_parser("grant")
    grant.add_argument("email")
    grant.add_argument("role", choices=("operator", "clinician"))
    actions.add_parser("revoke").add_argument("email")
    args = parser.parse_args()
    email = args.email.strip().lower()
    if not re.fullmatch(r"[^\s/@:]+@[^\s/@:]+\.[^\s/@:]+", email):
        parser.error("Enter an individual Google account email")
    gcloud = shutil.which("gcloud") or str(Path(os.environ.get("LOCALAPPDATA", "")) /
            "CHAKRA/BuildathonTools/google-cloud-sdk/bin/gcloud.cmd")
    blob = storage.Client(project=PROJECT).bucket(BUCKET).blob("accounts/" + hashlib.sha256(email.encode()).hexdigest() + ".json")
    if args.action == "revoke":
        try:
            blob.delete()
        except NotFound:
            pass
    verb = "add" if args.action == "grant" else "remove"
    subprocess.run([gcloud, "iap", "web", verb + "-iam-policy-binding", "--resource-type=cloud-run",
                    "--service=chakra-os", "--region=asia-south1", "--project=" + PROJECT,
                    "--member=user:" + email, "--role=roles/iap.httpsResourceAccessor", "--quiet"], check=True)
    if args.action == "grant":
        blob.upload_from_string(json.dumps({"email": email, "role": args.role, "hospital": "HOSP-CHENNAI-01"}),content_type="application/json")
    print("Updated CHAKRA backend account access.")


if __name__ == "__main__":
    main()
