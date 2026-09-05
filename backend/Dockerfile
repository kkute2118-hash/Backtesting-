# The backend as a container, for any host that is not Render.
#
# Nothing here is Render-specific: it reads the same environment variables as a
# local run, and it expects DATA_DB to point somewhere that survives a restart.
FROM python:3.11-slim

# libgomp is needed by scikit-learn's runtime; curl is used by the healthcheck.
RUN apt-get update \
 && apt-get install -y --no-install-recommends libgomp1 curl \
 && rm -rf /var/lib/apt/lists/*

WORKDIR /app

# Dependencies first, so a code change does not reinstall pandas every build.
COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

COPY app ./app

# The database lives on a mounted volume, never in the image: an image layer is
# replaced on every deploy, which would take the accumulated learning with it.
ENV DATA_DB=/data/market_data.sqlite3 \
    PYTHONUNBUFFERED=1
VOLUME ["/data"]

EXPOSE 8000
HEALTHCHECK --interval=30s --timeout=5s --start-period=20s \
  CMD curl -fsS http://localhost:8000/api/v1/health || exit 1

CMD ["sh", "-c", "uvicorn app.main:app --host 0.0.0.0 --port ${PORT:-8000}"]
