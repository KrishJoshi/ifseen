# ifseen in Docker

Run ifseen on a home server, NAS or Raspberry Pi with Docker Compose. One container runs
every rules file you give it and restarts with the machine.

The image is `ghcr.io/krishjoshi/ifseen` (tags `latest` and each version, e.g. `0.1.0`), built
for **amd64 and arm64**, so it runs on Raspberry Pi 4/5 (64-bit OS), Apple Silicon and most
NAS boxes. It includes the camera (OpenCV: RTSP, video files) and MQTT extras.

## Quick start

```bash
mkdir ifseen && cd ifseen
curl -fsSLO https://raw.githubusercontent.com/KrishJoshi/ifseen/main/docker/compose.yaml
curl -fsSL https://raw.githubusercontent.com/KrishJoshi/ifseen/main/docker/.env.example -o .env
mkdir rules
curl -fsSL https://raw.githubusercontent.com/KrishJoshi/ifseen/main/docker/rules/doorbell.yaml -o rules/doorbell.yaml
```

1. Open `.env` and set a provider key (`GEMINI_API_KEY`, free from
   [Google AI Studio](https://aistudio.google.com/apikey)), your camera's
   `DOORBELL_SNAPSHOT_URL` and an `NTFY_TOPIC` you've subscribed to in the
   [ntfy app](https://ntfy.sh).
2. Start it:

   ```bash
   docker compose up -d
   docker compose logs -f
   ```

No key yet? Set `IFSEEN_SERVE_ARGS=--dry-run` in `.env`: random probabilities, and actions are
logged instead of run.

## Adding rules

Every `rules/*.yaml` (or `.yml`) file is one watcher, all run by a single `ifseen serve`.
Add or edit a file, then `docker compose restart`. Rules files are the normal ifseen format
(see the [rules file reference](../README.md#rules-file-reference)) and can use any variable
from `.env` as `${NAME}`.

Camera sources that work in a container:

```yaml
source:
  url: http://frigate:5000/api/front_door/latest.jpg      # Frigate / IP camera snapshot
# camera: rtsp://user:pass@192.168.1.40:554/stream1        # RTSP stream
# url:                                                     # Home Assistant camera
#   url: http://homeassistant.local:8123/api/camera_proxy/camera.front_door
#   headers: {Authorization: "Bearer ${HA_TOKEN}"}
```

A built-in recipe works too: `ifseen init doorbell -o rules/doorbell.yaml` on any machine with
ifseen installed, or copy one from
[src/ifseen/recipes](https://github.com/KrishJoshi/ifseen/tree/main/src/ifseen/recipes).

For Home Assistant entities, add an `mqtt:` section to a rules file (see
[homeassistant.md](homeassistant.md)). On Home Assistant OS, use the add-on instead.

## The HTTP API

`ifseen serve` also exposes the [HTTP API](api.md) on port 8899, but only inside the container
by default. To reach it from other machines, set a token and listen on all interfaces in `.env`:

```bash
IFSEEN_TOKEN=a-long-random-string-16-plus
IFSEEN_SERVE_ARGS=--host 0.0.0.0
```

then uncomment the `ports:` block in `compose.yaml`. The healthcheck uses `/v1/health`.

## Upgrading

```bash
docker compose pull && docker compose up -d
```

To stay on a version, set `IFSEEN_TAG=0.1.0` in `.env`.

## One-off runs

```bash
docker run --rm -e GEMINI_API_KEY ghcr.io/krishjoshi/ifseen \
  "a parcel has been left on the doorstep" --url http://192.168.1.50/snapshot.jpg --ntfy my-topic
docker run --rm -v "$PWD:/work" -w /work ghcr.io/krishjoshi/ifseen test rules/doorbell.yaml --image door.jpg --provider mock
```

## Unraid, Portainer, Synology

- **Portainer**: Stacks > Add stack, paste `compose.yaml`, add the `.env` values under
  Environment variables, and put the rules folder on the host path you mount at `/rules`.
- **Unraid**: use the Compose Manager plugin with the same files, or add a container from
  `ghcr.io/krishjoshi/ifseen:latest` with a `/rules` path mapping, the env vars from
  `.env.example`, and post arguments `serve /rules/doorbell.yaml`.
- **Synology** (Container Manager): Project > Create, point it at a folder with `compose.yaml`,
  `.env` and `rules/`.

## What doesn't work in a container

- **Screen capture**: a container has no display. Run ifseen natively for `--screen`.
- **Microphone**: no audio device, and passing one through is platform-specific. Run natively
  for `--mic`.
- **USB webcams**: possible on Linux with `devices: ["/dev/video0:/dev/video0"]`, but a
  snapshot URL or RTSP stream is simpler.
- **Desktop notifications and `say`**: no desktop. Use `ntfy`, `webhook` or MQTT.
- **The free `local` provider** (torch) isn't in the image to keep it small.

## Building from source

```bash
git clone https://github.com/KrishJoshi/ifseen && cd ifseen
docker build -t ifseen .
```

Then set `image: ifseen` in `compose.yaml`.
