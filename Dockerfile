FROM python:3.11-slim
WORKDIR /app
ENV PYTHONPATH=/app PYTHONUNBUFFERED=1

# Longer timeout + retries so a slow connection doesn't kill a 40-minute build.
ENV PIP_DEFAULT_TIMEOUT=120 PIP_RETRIES=10 PIP_NO_CACHE_DIR=1

# CPU-only torch first: the default wheel pulls several GB of CUDA libraries we never use.
# Its own layer, so Docker caches it and a failed requirements install doesn't re-download it.
RUN pip install torch --index-url https://download.pytorch.org/whl/cpu

COPY requirements.txt .
RUN pip install -r requirements.txt

# Bake the embedding model into the image so containers start without downloading it.
RUN python -c "from sentence_transformers import SentenceTransformer; SentenceTransformer('all-MiniLM-L6-v2')"

COPY . .
