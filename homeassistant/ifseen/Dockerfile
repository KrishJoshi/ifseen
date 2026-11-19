ARG BUILD_FROM=ghcr.io/home-assistant/amd64-base-debian:bookworm

# Optional local wheels. The release workflow replaces this stage with the freshly built wheel
# (`docker buildx build --build-context wheels=dist/ ...`) so the image matches the release
# exactly, even before it's on PyPI. Left empty, ifseen comes from PyPI (or IFSEEN_PIP_SPEC).
FROM scratch AS wheels

FROM ${BUILD_FROM}
ARG BUILD_VERSION
# e.g. "ifseen[camera,mqtt] @ https://github.com/KrishJoshi/ifseen/archive/refs/tags/v0.1.0.tar.gz"
ARG IFSEEN_PIP_SPEC=""

RUN apt-get update \
    && apt-get install -y --no-install-recommends python3 python3-venv libglib2.0-0 \
    && rm -rf /var/lib/apt/lists/*

COPY --from=wheels / /tmp/wheels/
RUN set -e; \
    whl="$(ls /tmp/wheels/ifseen-*.whl 2>/dev/null | head -n 1 || true)"; \
    if [ -n "${whl}" ]; then spec="${whl}[camera,mqtt]"; \
    elif [ -n "${IFSEEN_PIP_SPEC}" ]; then spec="${IFSEEN_PIP_SPEC}"; \
    elif [ -n "${BUILD_VERSION}" ]; then spec="ifseen[camera,mqtt]==${BUILD_VERSION}"; \
    else echo "set BUILD_VERSION or IFSEEN_PIP_SPEC" >&2; exit 1; fi; \
    echo "installing ${spec}"; \
    python3 -m venv /opt/ifseen; \
    /opt/ifseen/bin/pip install --no-cache-dir "${spec}"; \
    rm -rf /tmp/wheels; \
    /opt/ifseen/bin/ifseen --version
ENV PATH="/opt/ifseen/bin:${PATH}"

COPY rootfs /
COPY run.sh /run.sh
RUN chmod a+x /run.sh /usr/bin/ifseen-addon-config

CMD ["/run.sh"]
