FROM python:3.11-slim
WORKDIR /app
COPY requirements.txt .
RUN apt-get update && apt-get upgrade -y \
    && apt-get install -y --no-install-recommends \
    tesseract-ocr \
    tesseract-ocr-jpn \
    poppler-utils \
    && rm -rf /var/lib/apt/lists/*
# Packaging tools (pip/setuptools/wheel and ensurepip's bundled wheels) are only needed at
# build time; drop them so their vendored copies (urllib3, msgpack, ...) don't ship.
RUN pip install --no-cache-dir -r requirements.txt \
    && pip uninstall -y pip setuptools wheel \
    && rm -rf /usr/local/lib/python3.11/ensurepip/_bundled
COPY . .
# SQLite (DATABASE_TYPE=sqlite, default) writes to ./data/app.db relative to WORKDIR=/app.
# Create the directory so Base.metadata.create_all() can open the DB file on Cloud Run.
RUN mkdir -p /app/data
ENV PORT=8080
EXPOSE 8080
CMD ["sh", "-c", "uvicorn app.main:app --host 0.0.0.0 --port ${PORT}"]
