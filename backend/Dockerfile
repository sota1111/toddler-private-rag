FROM python:3.11-slim
WORKDIR /app
COPY requirements.txt .
RUN apt-get update && apt-get install -y --no-install-recommends \
    tesseract-ocr \
    tesseract-ocr-jpn \
    poppler-utils \
    && rm -rf /var/lib/apt/lists/*
RUN pip install --no-cache-dir -r requirements.txt
COPY . .
# SQLite (DATABASE_TYPE=sqlite, default) writes to ./data/app.db relative to WORKDIR=/app.
# Create the directory so Base.metadata.create_all() can open the DB file on Cloud Run.
RUN mkdir -p /app/data
ENV PORT=8080
EXPOSE 8080
CMD ["sh", "-c", "uvicorn app.main:app --host 0.0.0.0 --port ${PORT}"]
