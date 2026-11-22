"""Compare downloaded weights with a reviewed digest before deserializing them."""

import hashlib
import json
from pathlib import Path


def verify_checkpoint(model_key, weights):
    allowed = json.loads(Path(__file__).with_name("checkpoint_hashes.json").read_text())
    digest = hashlib.sha256()
    with open(weights, "rb") as stream:
        for block in iter(lambda: stream.read(1024 * 1024), b""):
            digest.update(block)
    if digest.hexdigest() != allowed.get(model_key):
        raise ValueError("Checkpoint integrity verification failed")
