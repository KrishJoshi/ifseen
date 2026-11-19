ARG BUILD_FROM=ghcr.io/home-assistant/amd64-base-debian:bookworm
FROM ${BUILD_FROM}

RUN apt-get update \
    && apt-get install -y --no-install-recommends python3 python3-venv libglib2.0-0 \
    && rm -rf /var/lib/apt/lists/*

# The Supervisor builds with this folder as the context, so ifseen is installed from the repo
# archive rather than copied in. Override to pin a tag or test a local build.
ARG IFSEEN_PIP_SPEC="ifseen[camera,mqtt] @ https://github.com/KrishJoshi/ifseen/archive/refs/heads/main.tar.gz"
RUN python3 -m venv /opt/ifseen \
    && /opt/ifseen/bin/pip install --no-cache-dir "${IFSEEN_PIP_SPEC}" \
    && /opt/ifseen/bin/ifseen --version
ENV PATH="/opt/ifseen/bin:${PATH}"

COPY rootfs /
COPY run.sh /run.sh
RUN chmod a+x /run.sh /usr/bin/ifseen-addon-config

CMD ["/run.sh"]
