FROM python:3.11-slim

WORKDIR /app

# Install deps in a separate layer so rebuilds don't reinstall on code-only changes
COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

COPY . .

# Ensure the storage directory exists so SQLite can create the DB file
RUN mkdir -p /app/storage

EXPOSE 8000

CMD ["uvicorn", "agent.main:app", "--host", "0.0.0.0", "--port", "8000"]
