# Headless ifseen for cameras, snapshot URLs and files (no screen or mic inside a container).
# Built from this source tree; published multi-arch as ghcr.io/krishjoshi/ifseen.
FROM python:3.12-slim AS build
WORKDIR /src
COPY pyproject.toml README.md LICENSE ./
COPY src ./src
RUN pip wheel --no-cache-dir --no-deps --wheel-dir /wheels .

FROM python:3.12-slim
LABEL org.opencontainers.image.title="ifseen" \
      org.opencontainers.image.description="Plain-English triggers for your cameras, powered by decision models" \
      org.opencontainers.image.source="https://github.com/KrishJoshi/ifseen" \
      org.opencontainers.image.licenses="MIT"
# opencv-python-headless still links against glib.
RUN apt-get update \
    && apt-get install -y --no-install-recommends libglib2.0-0 \
    && rm -rf /var/lib/apt/lists/*
COPY --from=build /wheels /wheels
RUN whl="$(ls /wheels/ifseen-*.whl)" \
    && pip install --no-cache-dir "${whl}[camera,mqtt]" \
    && rm -rf /wheels \
    && ifseen --version

RUN useradd --create-home ifseen
USER ifseen
WORKDIR /home/ifseen
ENV PYTHONUNBUFFERED=1
ENTRYPOINT ["ifseen"]
CMD ["--help"]
