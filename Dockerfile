# Traffic Agent dashboard. CPU only; see docs/DEPLOYMENT.md for GPU notes.
FROM python:3.11-slim

ENV PYTHONUNBUFFERED=1 \
    PIP_NO_CACHE_DIR=1 \
    APP_ENV=production \
    TRAFFIC_AGENT_DATA_DIR=/data \
    PORT=8501

RUN apt-get update \
    && apt-get install -y --no-install-recommends ffmpeg libglib2.0-0 \
    && rm -rf /var/lib/apt/lists/*

WORKDIR /app

# CPU-only PyTorch first: the default wheel pulls in gigabytes of CUDA.
RUN pip install torch torchvision --index-url https://download.pytorch.org/whl/cpu

# Headless OpenCV (no display libraries); it replaces opencv-python.
COPY requirements.txt requirements-plates.txt ./
RUN grep -v '^opencv-python' requirements.txt > requirements.docker.txt \
    && pip install -r requirements.docker.txt opencv-python-headless

# License-plate reading is optional (adds EasyOCR, about 1 GB with its model):
#   docker compose build --build-arg WITH_PLATES=1
ARG WITH_PLATES=0
RUN if [ "$WITH_PLATES" = "1" ]; then pip install easyocr; fi

COPY . .

# Bake the base detector into the image so the first request does not
# have to download it.
RUN python -c "from ultralytics import YOLO; YOLO('yolov8n.pt')" \
    && mkdir -p /data \
    && useradd --create-home app \
    && chown -R app:app /app /data

USER app
VOLUME ["/data"]
EXPOSE 8501

HEALTHCHECK --interval=30s --timeout=5s --start-period=60s --retries=3 \
    CMD python -c "import os,urllib.request as u; u.urlopen('http://localhost:%s/_stcore/health' % os.environ.get('PORT','8501'), timeout=4)"

CMD ["sh", "-c", "streamlit run app/main.py --server.port=${PORT} --server.address=0.0.0.0 --server.headless=true"]
