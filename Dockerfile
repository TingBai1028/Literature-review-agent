FROM python:3.11-slim

WORKDIR /app

# Dependencies are installed at build time; nothing is installed or downloaded at runtime.
COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

# Bake the Clusterer's embedding model into the image (keep in sync with config.EMBEDDING_MODEL;
# tests/test_clusterer.py checks it), so the container never downloads a model at runtime.
ARG EMBEDDING_MODEL=BAAI/bge-small-en-v1.5
ENV EMBEDDING_CACHE_DIR=/app/models
RUN python -c "from fastembed import TextEmbedding; TextEmbedding('${EMBEDDING_MODEL}', cache_dir='/app/models')"

COPY . .
RUN mkdir -p /app/logs

# Zetaris and Nightshift run outside this container: point their URLs at
# host.docker.internal instead of localhost (see .env.example).
ENV PORT=8000
EXPOSE 8000

CMD ["python", "run.py"]
