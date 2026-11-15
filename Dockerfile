FROM python:3.12-slim

ENV PYTHONUNBUFFERED=1 \
    PIP_NO_CACHE_DIR=1 \
    HF_HOME=/models/hf

WORKDIR /app

RUN apt-get update && apt-get install -y --no-install-recommends libgomp1 && rm -rf /var/lib/apt/lists/*

# torch: force CPU wheels to keep the image small; installed before requirements
# so that requirements.txt changes do not invalidate the torch layer
RUN pip install --no-cache-dir torch==2.8.0 --index-url https://download.pytorch.org/whl/cpu

COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

COPY alembic.ini pyproject.toml* pytest.ini* ./
COPY migrations ./migrations
COPY backend ./backend
COPY api.py .
COPY frontend ./frontend
COPY scripts ./scripts
COPY ["resource data", "./resource data"]

EXPOSE 8012

# single api instance: alembic upgrade + model cache bootstrap are safe at start
CMD ["bash", "scripts/entrypoint.sh"]
