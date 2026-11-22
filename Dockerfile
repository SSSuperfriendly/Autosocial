FROM node:22-alpine AS frontend
WORKDIR /build
COPY frontend/package.json frontend/package-lock.json ./
RUN npm ci
COPY frontend/ ./
RUN npm run build

FROM python:3.12-slim
ENV PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1 \
    PYTHONPATH=/app \
    AUTOSOCIAL_REQUIRE_AUTH=true \
    DATABASE_PATH=/state/data/autosocial.db \
    ATTACHMENT_DIR=/state/data/attachments
RUN apt-get update \
    && apt-get install -y --no-install-recommends ca-certificates curl \
    && rm -rf /var/lib/apt/lists/* \
    && groupadd --gid 10001 autosocial \
    && useradd --uid 10001 --gid autosocial --no-create-home autosocial \
    && mkdir -p /state \
    && chown autosocial:autosocial /state
WORKDIR /app
COPY requirements.txt ./
RUN pip install --no-cache-dir -r requirements.txt
COPY autosocial/ ./autosocial/
COPY server/ ./server/
COPY scripts/ ./scripts/
COPY student_profile.example.md ./
COPY --from=frontend /build/dist ./frontend/dist/
WORKDIR /state
USER autosocial
VOLUME ["/state"]
EXPOSE 8000
HEALTHCHECK --interval=30s --timeout=5s --start-period=15s --retries=3 \
    CMD python -c "import urllib.request; urllib.request.urlopen('http://127.0.0.1:8000/health', timeout=3)"
CMD ["python", "-m", "uvicorn", "server.main:app", "--host", "0.0.0.0", "--port", "8000", "--workers", "1"]
