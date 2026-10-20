FROM node:22-alpine AS frontend-build

WORKDIR /build/frontend
COPY frontend/package.json frontend/package-lock.json ./
RUN npm ci
COPY frontend/ ./
RUN npm run build

FROM python:3.13-slim

ENV PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1 \
    PIP_NO_CACHE_DIR=1 \
    FOOTAGE_PROVIDER=pixabay \
    TTS_PROVIDER=pyttsx3 \
    REAL_RENDERING=true

RUN apt-get update \
    && apt-get install --no-install-recommends -y ffmpeg espeak libespeak1 fonts-dejavu-core \
    && rm -rf /var/lib/apt/lists/*

WORKDIR /app
COPY requirements.txt ./
RUN pip install -r requirements.txt
COPY app/ ./app/
COPY --from=frontend-build /build/frontend/dist ./frontend/dist

RUN mkdir -p /app/data/jobs

CMD ["sh", "-c", "uvicorn app.main:app --host 0.0.0.0 --port ${PORT:-10000}"]
