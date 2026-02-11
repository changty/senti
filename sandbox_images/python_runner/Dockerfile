FROM python:3.12-slim

RUN pip install --no-cache-dir numpy pandas

WORKDIR /app
COPY run.py .

USER nobody
CMD ["python", "run.py"]
