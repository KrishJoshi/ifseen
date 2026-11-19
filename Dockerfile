# Headless ifseen for cameras and snapshot URLs (no screen or mic inside a container).
FROM python:3.12-slim

RUN apt-get update \
    && apt-get install -y --no-install-recommends libgl1 libglib2.0-0 \
    && rm -rf /var/lib/apt/lists/*

WORKDIR /app
COPY pyproject.toml README.md LICENSE ./
COPY src ./src
RUN pip install --no-cache-dir ".[camera,mqtt]"

RUN useradd --create-home ifseen
USER ifseen
ENTRYPOINT ["ifseen"]
CMD ["--help"]
