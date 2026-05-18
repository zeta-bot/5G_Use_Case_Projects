FROM python:3.10-slim

ENV PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1 \
    PIP_NO_CACHE_DIR=1 \
    MEDIAPIPE_DISABLE_GPU=1 \
    TTS_BACKEND=pyttsx3 \
    ALLOW_TTS_FALLBACK=1 \
    CAMERA_SOURCE=0

WORKDIR /app

RUN apt-get update && apt-get install -y --no-install-recommends \
    libglib2.0-0 \
    libsm6 \
    libxext6 \
    libxrender1 \
    libgl1 \
    libgomp1 \
    libsndfile1 \
    ffmpeg \
    espeak-ng \
    libespeak1 \
    libasound2 \
    libportaudio2 \
    && rm -rf /var/lib/apt/lists/*

COPY requirements.txt /app/requirements.txt
RUN python -m pip install --upgrade pip && pip install -r /app/requirements.txt

COPY . /app

# Lightweight default: runs app with pyttsx3 backend (via env TTS_BACKEND).
CMD ["python", "app/main.py"]
