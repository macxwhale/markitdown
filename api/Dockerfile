# Standalone image for the MarkItDown HTTP API.
#
# Build from the repository root so the build context includes packages/:
#   docker build -f api/Dockerfile -t markitdown-api .
# (docker-compose.yml at the repo root does this for you)

FROM python:3.13-slim-bookworm

ENV DEBIAN_FRONTEND=noninteractive
ENV EXIFTOOL_PATH=/usr/bin/exiftool
ENV FFMPEG_PATH=/usr/bin/ffmpeg
ENV PYTHONUNBUFFERED=1

# Runtime dependencies used by the audio/image converters
RUN apt-get update && apt-get install -y --no-install-recommends \
    ffmpeg \
    exiftool \
    && rm -rf /var/lib/apt/lists/*

WORKDIR /app

# Install the markitdown package (with all optional converters) plus the API's
# own dependencies. Copying the whole repo keeps this in step with local edits
# to packages/markitdown without needing a published release.
COPY packages /app/packages
COPY api /app/api

RUN pip install --no-cache-dir \
    /app/packages/markitdown[all] \
    -r /app/api/requirements.txt

ARG USERID=nobody
ARG GROUPID=nogroup
USER $USERID:$GROUPID

EXPOSE 8000

ENTRYPOINT ["uvicorn", "api.main:app", "--app-dir", "/app", "--host", "0.0.0.0", "--port", "8000"]
