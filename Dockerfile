FROM python:3.11-slim

WORKDIR /app

# Optional: gd_auth via PIP_EXTRA_INDEX_URL or by placing wheel(s) in wheels/ (see scripts/build_gd_auth_wheel.sh)
ARG PIP_EXTRA_INDEX_URL=

ENV PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1

# Install dependencies
COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

# Install gd_auth from internal PyPI (if PIP_EXTRA_INDEX_URL is set)
RUN if [ -n "$PIP_EXTRA_INDEX_URL" ]; then \
      pip install --no-cache-dir gd_auth --extra-index-url "$PIP_EXTRA_INDEX_URL"; \
    fi

# Install gd_auth from local wheel (recommended: run scripts/build_gd_auth_wheel.sh on host first)
COPY wheels/ /tmp/wheels/
RUN if ls /tmp/wheels/*.whl 1>/dev/null 2>&1; then pip install --no-cache-dir /tmp/wheels/*.whl; fi

# Copy the application code
COPY . .

# Expose the port the app runs on
EXPOSE 8000

# Command to run the application
CMD ["uvicorn", "main:app", "--host", "0.0.0.0", "--port", "8000"]
