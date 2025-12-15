FROM python:3.11-slim

# Ensure logs are streamed to Cloud Logging
ENV PYTHONUNBUFFERED=1


WORKDIR /app

# Install system dependencies if needed (e.g. for some python packages)
# RUN apt-get update && apt-get install -y --no-install-recommends gcc && rm -rf /var/lib/apt/lists/*

COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

# Copy source code and config
COPY src/ ./src/
COPY credentials.json .
COPY .env .
COPY token.json .

# Add /app to PYTHONPATH so we can import 'src' as a package
ENV PYTHONPATH=/app

# Run the web service on container startup using gunicorn
CMD ["gunicorn", "--bind", ":8080", "--workers", "1", "--threads", "8", "--timeout", "0", "src.app:app"]
