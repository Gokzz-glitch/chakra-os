FROM python:3.11-slim
WORKDIR /app
COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt
COPY security_windows.py pathology_journal.py security_settings.py clinical_access.py evaluation_map.py clinical_pipeline.py main.py index_v1.html admin.html phone.html doctor.html ./
COPY templates/ ./templates/
COPY static/ ./static/
RUN useradd --system --create-home appuser
USER appuser
CMD ["sh", "-c", "uvicorn main:app --no-access-log --no-proxy-headers --host 0.0.0.0 --ws-max-size 6991000 --port ${PORT:-8080}"]
