FROM python:3.11-slim

WORKDIR /app

# Dependencies are installed at build time; nothing is installed or downloaded at runtime.
COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

COPY . .
RUN mkdir -p /app/logs

# Zetaris and Nightshift run outside this container: point their URLs at
# host.docker.internal instead of localhost (see .env.example).
ENV PORT=8000
EXPOSE 8000

CMD ["python", "run.py"]
