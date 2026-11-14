FROM python:3.12-slim

ENV PYTHONUNBUFFERED=1 \
    PIP_NO_CACHE_DIR=1 \
    HF_HOME=/models/hf

WORKDIR /app

RUN apt-get update && apt-get install -y --no-install-recommends libgomp1 && rm -rf /var/lib/apt/lists/*

# torch: force CPU wheels to keep the image small
COPY requirements.txt .
RUN pip install --no-cache-dir torch==2.8.0 --index-url https://download.pytorch.org/whl/cpu \
    && pip install --no-cache-dir -r requirements.txt

COPY alembic.ini pyproject.toml* pytest.ini* ./
COPY migrations ./migrations
COPY backend ./backend
COPY api.py .
COPY frontend ./frontend
COPY web ./web
COPY scripts ./scripts
COPY "resource data" "./resource data"

EXPOSE 8012

# single api instance: alembic upgrade is safe to run at container start
CMD ["sh", "-c", "alembic upgrade head && uvicorn api:app --host 0.0.0.0 --port 8012"]
