FROM python:3.12-slim

WORKDIR /app

# Copy source and config
COPY pyproject.toml .
COPY src/ src/
COPY config/ config/

# Install package and dependencies
RUN pip install --no-cache-dir .

# Create data directory
RUN mkdir -p data/logs

CMD ["python", "-m", "senti"]
