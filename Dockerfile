# VCB_AI — planner, footage match, FFmpeg render
#
#   docker build -t vcb-ai:latest .
#   docker tag  vcb-ai:latest <registry>/vcb-ai:latest
#   docker push <registry>/vcb-ai:latest
#
# Runtime: mount media + (tuỳ chọn) data, truyền secret qua env — đừng bake .env vào image.
#   -v $PWD/media:/app/media -v $PWD/data:/app/data
#   -e ASSISTANT_INTERNAL_SECRET=... -e MINIMAX_API_KEY=...

FROM python:3.11-slim-bookworm

WORKDIR /app

RUN apt-get update && apt-get install -y --no-install-recommends \
        ffmpeg \
        fonts-noto-core \
        fonts-dejavu-core \
        ca-certificates \
    && rm -rf /var/lib/apt/lists/*

COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

COPY main.py .
COPY src ./src
COPY assets ./assets
COPY data/sample-scripts.json data/ai-models-pricing.json data/catalog.json ./data/

ENV HOST=0.0.0.0 \
    PORT=8787 \
    RELOAD=0 \
    PYTHONUNBUFFERED=1 \
    VCB_FONT_FILE=/usr/share/fonts/truetype/noto/NotoSans-Regular.ttf \
    VCB_FONT_DIR=/usr/share/fonts/truetype/noto

EXPOSE 8787

HEALTHCHECK --interval=30s --timeout=5s --start-period=20s --retries=3 \
    CMD python -c "import urllib.request; urllib.request.urlopen('http://127.0.0.1:8787/health', timeout=4)"

CMD ["python", "-u", "main.py"]
