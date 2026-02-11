FROM python:3.12-slim

RUN pip install --no-cache-dir numpy pandas

WORKDIR /app
COPY run.py .

RUN mkdir -p /data/upload && chmod 755 /data/upload

USER nobody
CMD ["python", "run.py"]
