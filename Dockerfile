FROM python:3.12-slim

WORKDIR /app

# Install system deps: CA certs + curl (healthcheck) + build tools (web3/greenlet need gcc)
RUN apt-get update \
    && apt-get install -y --no-install-recommends \
        curl ca-certificates gcc g++ libffi-dev \
    && rm -rf /var/lib/apt/lists/*

COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

COPY . .

RUN mkdir -p /app/storage

# Use system CA bundle so a full/corrupt Docker overlay can't break HTTPS via certifi
ENV SSL_CERT_FILE=/etc/ssl/certs/ca-certificates.crt
ENV REQUESTS_CA_BUNDLE=/etc/ssl/certs/ca-certificates.crt

EXPOSE 8000

HEALTHCHECK --interval=30s --timeout=10s --start-period=25s --retries=3 \
  CMD curl -sf http://localhost:8000/health || exit 1

CMD ["uvicorn", "agent.main:app", "--host", "0.0.0.0", "--port", "8000", "--workers", "1"]
