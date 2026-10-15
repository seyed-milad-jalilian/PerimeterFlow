FROM python:3.12-slim-bookworm

RUN apt-get update && apt-get install -y --no-install-recommends \
    sumo \
    sumo-tools \
    curl \
    ca-certificates \
    && rm -rf /var/lib/apt/lists/*

ENV SUMO_HOME=/usr/share/sumo
ENV PYTHONUNBUFFERED=1

WORKDIR /app

RUN groupadd -g 10001 perimeter && \
    useradd -u 10001 -g perimeter -s /bin/bash -m perimeter

COPY pyproject.toml README.md ./
COPY src/ ./src/
RUN pip install --no-cache-dir .

COPY configs/ ./configs/
COPY data/ ./data/
COPY report/ ./report/
RUN mkdir -p /app/results && chown -R perimeter:perimeter /app

USER 10001

ENTRYPOINT ["python", "-m", "perimeterflow.cli"]
CMD ["--help"]
