FROM python:3.9-slim

LABEL maintainer="M3U to STRM Converter"
LABEL description="Flask application that converts M3U playlists to STRM files"

# Install system dependencies
RUN apt-get update && apt-get install -y --no-install-recommends \
    curl \
    && rm -rf /var/lib/apt/lists/*

# Create app user with UID/GID 1000 (matching host permissions)
RUN groupadd -g 1000 appuser && \
    useradd -u 1000 -g appuser -s /bin/bash -m appuser

WORKDIR /app

# Create necessary directories
RUN mkdir -p data logs content uploads static/css static/js templates && \
    chown -R appuser:appuser /app

# Copy Python dependencies and install
COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

# Copy Python files
COPY *.py ./

# Copy all template and static files directly (no wildcards)
COPY templates/ /app/templates/
COPY static/ /app/static/

# Create placeholder index.html if it doesn't exist
RUN if [ ! -f /app/templates/index.html ]; then \
        echo '<html><body><h1>M3U to STRM Converter</h1></body></html>' > /app/templates/index.html; \
    fi

# Ensure proper permissions for all files and directories
RUN chown -R appuser:appuser /app && \
    chmod -R 755 /app && \
    # Make specific directories writable
    chmod 777 /app/logs && \
    chmod 777 /app/data && \
    chmod 777 /app/uploads && \
    chmod 777 /app/content

# Switch to app user
USER appuser

# Create necessary empty files with proper permissions
RUN touch /app/logs/app.log && \
    chmod 666 /app/logs/app.log

# Expose port
EXPOSE 8768

# Set environment variables
ENV PYTHONUNBUFFERED=1

# Health check
HEALTHCHECK --interval=30s --timeout=10s --start-period=5s --retries=3 \
  CMD curl -f http://localhost:8768/ || exit 1

# Command to run the application
CMD ["python", "app.py"]
