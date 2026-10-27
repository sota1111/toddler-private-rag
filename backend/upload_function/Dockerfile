# SOT-1376: Cloud Run upload service (upload-api). Wraps the existing functions-framework app
# (main.py:upload_attachment) so the same upload logic runs as an always-warm Cloud Run service
# (min-instances=1) instead of a gen2 Cloud Function. main.py is unchanged — the public contract
# (POST /api/info/{id}/attachments, auth_token Cookie HMAC, multipart, GCS save, Firestore pending,
# /internal/process-ocr dispatch) and its tests stay intact.
FROM python:3.11-slim

WORKDIR /app

# Pull OS security patches newer than the base image.
RUN apt-get update && apt-get upgrade -y && rm -rf /var/lib/apt/lists/*

COPY requirements.txt .
RUN pip install --no-cache-dir --upgrade pip setuptools wheel \
    && pip install --no-cache-dir -r requirements.txt

COPY . .

ENV PORT=8080
# functions-framework provides a production WSGI server (gunicorn) for Cloud Run.
CMD exec functions-framework --target=upload_attachment --source=main.py --port=$PORT
