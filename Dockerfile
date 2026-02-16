FROM python:3.12-slim

WORKDIR /app

# Build argument for version
ARG BUILD_VERSION=dev
ENV APP_VERSION=${BUILD_VERSION}

# Disable Python output buffering for proper logging in Docker
ENV PYTHONUNBUFFERED=1

# Install Python dependencies
COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

# Copy application code
COPY app/ ./app/

EXPOSE 8000

CMD ["uvicorn", "app.main:app", "--host", "0.0.0.0", "--port", "8000"]
