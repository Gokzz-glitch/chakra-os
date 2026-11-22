FROM asia-southeast1-docker.pkg.dev/girpolypposframesrealcolon/cloud-run-source-deploy/chakra-vision@sha256:4868a798e3aed13606b4a3210506c82a80b3e2d0eeae4e6b17fe1d84a9e502ce
WORKDIR /eval
RUN pip install --no-cache-dir timm google-cloud-storage imageio-ffmpeg einops
COPY vendor vendor
COPY worker.py checkpoint_hashes.json checkpoint_integrity.py replay_validation.py ./
RUN useradd --system --create-home appuser
USER appuser
CMD ["python","-u","worker.py"]
