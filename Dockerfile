# One image that serves both the API and the built frontend on one port.
#
# This is the portable unit of deployment for this project. It carries the trained
# model, the baked department profiles and the open-data cache, so a container started
# from it is immediately useful with no network access to any open-data API.
#
#   docker build -t hi-protein .
#   docker run -p 8080:8080 hi-protein
#
# Then open http://localhost:8080/ — app at /, API at /api/v1, docs at /docs.

# --- Stage 1: build the frontend bundle --------------------------------------
FROM node:20-slim AS web

WORKDIR /build
COPY frontend/package.json frontend/package-lock.json ./
RUN npm ci --no-audit --no-fund

COPY frontend/ ./
# Leave VITE_API_BASE unset: the API is served by the same process as this bundle, so
# the frontend resolves it relative to the page it was loaded from. Set it only when the
# two are split across origins, as they are with a Vercel frontend — see
# docs/DEPLOYMENT.md.
ARG VITE_API_BASE=""
RUN npm run build


# --- Stage 2: the runtime ----------------------------------------------------
FROM python:3.11-slim AS runtime

ENV PYTHONUNBUFFERED=1 \
    PYTHONDONTWRITEBYTECODE=1 \
    PIP_NO_CACHE_DIR=1 \
    PORT=8080

WORKDIR /app

# xgboost declares a hard dependency on nvidia-nccl-cu12 — 471 MB of CUDA libraries
# that nothing in this project uses, since the model is a CPU-trained quantile ensemble
# scored one request at a time. `xgboost-cpu` is the same release built without GPU
# support and unpickles the existing artifact identically.
#
# It has to be substituted INTO the requirements file rather than pre-installed
# alongside it: pip matches on distribution name, so an already-present `xgboost-cpu`
# does not satisfy the `xgboost==3.2.0` pin and the CUDA wheel comes back. Rewriting the
# line keeps requirements.txt as the single source of truth for the version.
#
# Measured on linux/arm64, 2026-11-02: 1.32 GB image before this, 605 MB after.
COPY requirements.txt ./
RUN sed 's/^xgboost==/xgboost-cpu==/' requirements.txt > /tmp/requirements-runtime.txt \
 && pip install --no-cache-dir -r /tmp/requirements-runtime.txt \
 && rm /tmp/requirements-runtime.txt

# Application code and the committed derived artifacts.
COPY backend/ ./backend/
COPY ml/ ./ml/
COPY scripts/ ./scripts/
COPY data/processed/ ./data/processed/

# Optional: the open-data response cache. If you have a warm data/cache/ locally,
# un-ignore it in .dockerignore and the image can run fully offline with
# HIPROTEIN_OFFLINE=1. Left out of the default build because it is ~49 MB and the app
# fetches what it needs on demand.
# COPY data/cache/ ./data/cache/

COPY --from=web /build/dist ./frontend/dist

# Read-only application, so it has no reason to run as root.
RUN useradd --create-home --uid 10001 app \
 && mkdir -p data/cache \
 && chown -R app:app /app
USER app

EXPOSE 8080

# The container platform's health check should hit this. It reports whether the model
# unpickled, how many department weather panels loaded, and which profile horizons are
# baked — which is every setup question in one call.
HEALTHCHECK --interval=30s --timeout=10s --start-period=40s --retries=3 \
  CMD python -c "import urllib.request,os,sys; \
sys.exit(0 if urllib.request.urlopen(f\"http://127.0.0.1:{os.environ['PORT']}/health\", timeout=8).status == 200 else 1)"

# One worker on purpose. Each one unpickles its own copy of the yield model and warms
# its own profile caches, so a second worker doubles the memory for no throughput gain
# on a demo-sized deployment. Scale by running more containers.
CMD ["sh", "-c", "python -m uvicorn app.main:app --app-dir backend --host 0.0.0.0 --port ${PORT}"]
