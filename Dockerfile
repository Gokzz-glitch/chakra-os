FROM python:3.11-slim
WORKDIR /app
COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt
COPY clinical_pipeline.py main.py index_v1.html admin.html phone.html doctor.html ./
COPY templates/ ./templates/
COPY static/ ./static/
CMD ["sh", "-c", "uvicorn main:app --host 0.0.0.0 --port ${PORT:-8080}"]
