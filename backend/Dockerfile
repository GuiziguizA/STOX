# ── Stage 1 : dépendances ────────────────────────────────────────────────────
FROM python:3.12-slim AS deps

WORKDIR /app

ENV PYTHONUNBUFFERED=1 \
    PYTHONDONTWRITEBYTECODE=1 \
    PIP_NO_CACHE_DIR=1

COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

# ── Stage 2 : développement (hot-reload, code monté en volume) ───────────────
FROM deps AS dev

CMD ["uvicorn", "app.main:app", "--reload", "--host", "0.0.0.0", "--port", "8000"]

# ── Stage 3 : production (code copié, 2 workers) ─────────────────────────────
FROM deps AS prod

COPY . .

CMD ["uvicorn", "app.main:app", "--host", "0.0.0.0", "--port", "8000", "--workers", "2"]
