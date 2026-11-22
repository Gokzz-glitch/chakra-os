"""Read-only CHAKRA OS release checks. Run with Python 3 in Google Cloud Shell."""
import json
import os
from pathlib import Path
import shutil
import subprocess
import sys
from urllib.error import HTTPError
from urllib.parse import urlsplit
from urllib.request import HTTPRedirectHandler, build_opener, urlopen

PROJECT = "girpolypposframesrealcolon"
SERVICE = "chakra-os"
REGION = "asia-south1"


def gcloud(*args):
    executable = shutil.which("gcloud") or str(
        Path(os.environ.get("LOCALAPPDATA", "")) /
        "CHAKRA/BuildathonTools/google-cloud-sdk/bin/gcloud.cmd"
    )
    output = subprocess.check_output(
        [executable, "run", "services", *args, SERVICE, "--project", PROJECT,
         "--region", REGION, "--format=json"], text=True, timeout=60
    )
    return json.loads(output)


def main():
    service = gcloud("describe")
    policy = gcloud("get-iam-policy")
    status = service["status"]
    template = service["spec"]["template"]
    annotations = service["metadata"].get("annotations", {})
    checks = []

    def check(name, passed, evidence):
        checks.append(bool(passed))
        print(f"{'PASS' if passed else 'FAIL'} | {name} | {evidence}")

    ready = next((c["status"] for c in status["conditions"] if c["type"] == "Ready"), None)
    revision = status["latestReadyRevisionName"]
    check("Service is ready", ready == "True", revision)
    routed = sum(t.get("percent", 0) for t in status["traffic"] if t.get("revisionName") == revision)
    check("Verified revision receives all traffic", routed == 100, f"{routed}%")
    minimum = max(int(annotations.get("run.googleapis.com/minScale", 0)),
                  int(template["metadata"].get("annotations", {}).get("autoscaling.knative.dev/minScale", 0)))
    check("CPU service can scale to zero", minimum == 0, f"configured minimum {minimum}")

    broad = any(b["role"] == "roles/run.invoker" and
                set(b["members"]) & {"allUsers", "allAuthenticatedUsers"} for b in policy.get("bindings", []))
    private = not broad and annotations.get("run.googleapis.com/invoker-iam-disabled") != "true"
    iap = annotations.get("run.googleapis.com/iap-enabled") == "true"
    check("Real-patient release gate: restricted platform entry", private or iap,
          f"broad invoker binding={broad}, IAP={iap}. App-level clinical authorization requires a separate test.")
    # Read the advertised demo page only. Do not call patient routes or GPU/model endpoints.
    if broad and not iap:
        with urlopen(status["url"] + "/v2/doctor", timeout=30) as response:
            content = response.read(1_000_000).decode().lower()
            check("Public synthetic doctor page renders", response.status == 200 and
                  "text/html" in response.headers.get("Content-Type", "") and "chakra" in content,
                  f"HTTP {response.status}")
    elif private and not iap:
        for endpoint in [status["url"]] + [t["url"] for t in status["traffic"] if t.get("url")]:
            try:
                with urlopen(endpoint + "/v2/doctor", timeout=30) as response:
                    code = response.status
            except HTTPError as error:
                code = error.code
            check("Anonymous doctor-page access denied", code in (401, 403), f"{endpoint} HTTP {code}")
    else:
        class NoRedirect(HTTPRedirectHandler):
            def redirect_request(self, *args):
                return None

        opener = build_opener(NoRedirect())
        try:
            with opener.open(status["url"] + "/v2/doctor", timeout=30) as response:
                code, location = response.status, ""
        except HTTPError as error:
            code, location = error.code, error.headers.get("Location", "")
        check("IAP redirects anonymous browser to Google sign-in",
              code in (302, 303, 307) and urlsplit(location).hostname == "accounts.google.com",
              f"HTTP {code}. An approved account must also complete the browser flow.")
    return 0 if all(checks) else 1


if __name__ == "__main__":
    sys.exit(main())
