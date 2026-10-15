FROM python:3.12-slim-bookworm

# Install SUMO headless binary and system libraries
RUN apt-get update && apt-get install -y --no-install-recommends \
    sumo \
    sumo-tools \
    curl \
    ca-certificates \
    && rm -rf /var/lib/apt/lists/*

ENV SUMO_HOME=/usr/share/sumo
ENV PYTHONUNBUFFERED=1
# The repository is a virtual uv project (never built/installed); the package
# is imported directly from src/.
ENV PYTHONPATH=/app/src

WORKDIR /app

# Non-root user enforcement
RUN groupadd -g 10001 perimeter && \
    useradd -u 10001 -g perimeter -s /bin/bash -m perimeter

# Locked dependency install first for layer caching.
COPY pyproject.toml uv.lock ./
RUN pip install --no-cache-dir uv && \
    uv export --format requirements-txt --no-dev --no-emit-project -o /tmp/requirements.txt && \
    pip install --no-cache-dir -r /tmp/requirements.txt

COPY . .
RUN chown -R perimeter:perimeter /app

USER 10001

ENTRYPOINT ["python", "-m", "perimeterflow.cli"]
CMD ["--help"]
