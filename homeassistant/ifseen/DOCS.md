# ifseen

ifseen watches a camera, asks a decision model your plain-English rules every few seconds,
and publishes the answers to Home Assistant over MQTT. Each rules file becomes a device with:

- a **binary sensor** per rule: on from the moment it fires until it clears,
- a **probability sensor** per rule (%),
- a **trigger event**, a **last trigger** camera with the frame that fired, a **watching**
  switch to pause it (no captures, no cost) and status / cost diagnostics.

## Setup

1. Install the **Mosquitto broker** add-on (and the MQTT integration) if you don't have a
   broker. ifseen finds it automatically.
2. Pick a **provider** below and paste its API key. A free Gemini key from
   <https://aistudio.google.com/apikey> is the easiest. Turn on **Dry run** to try everything
   with random probabilities and no key.
3. Start the add-on once. It writes `front-door.yaml.example` to its config folder and stops.
   That folder is `/addon_configs/xxxxxxxx_ifseen/` (open it with the File editor, Samba or
   VS Code add-ons). Rename the file to `front-door.yaml`, change the camera and rules, and
   start the add-on again.

Every `*.yaml` file in the folder is one watcher and one device, named after the file.

```yaml
# front-door.yaml
source:
  url:
    url: http://supervisor/core/api/camera_proxy/camera.front_door
    headers:
      Authorization: Bearer ${SUPERVISOR_TOKEN}
every: 3s
rules:
  - name: person-at-door
    when: A person is standing at the front door.
    threshold: 0.85
    for: 2
    ha_device_class: occupancy
  - name: parcel-left
    when: A parcel or package has been left on the doorstep.
    threshold: 0.85
    for: 2
    cooldown: 10m
```

This gives you `binary_sensor.front_door_person_at_door`,
`sensor.front_door_parcel_left_probability`, `camera.front_door_last_trigger`,
`switch.front_door_watching` and friends. `camera_proxy` works for any camera entity, and
`${SUPERVISOR_TOKEN}` is provided by the add-on, so no long-lived token is needed. An RTSP
stream works too: `source: {camera: "rtsp://user:pass@192.168.1.40/stream"}`.

Rules files use the normal ifseen format (see the
[README](https://github.com/KrishJoshi/ifseen#rules-file-reference)). A file without
`mqtt:` uses the add-on's broker and a file without `provider:` uses the add-on's provider.
Rules without `then:` only update their entities: build automations in Home Assistant.

## Options

| option | |
|---|---|
| `provider` | `auto` (first provider with a key), `gemini`, `jev`, `azure`, `systemone`, `openai`, `ollama` or `mock` |
| `gemini_api_key`, `typesafe_api_key`, `openai_api_key`, `azure_decision_*`, `openai_base_url` | provider credentials, passed as environment variables |
| `rules_path` | folder of rules files (default `/config`, this add-on's folder) or a single file. Your HA config is at `/homeassistant` (read-only) |
| `rules` | optional: a whole rules file pasted as YAML, run in addition |
| `name` | device id for `rules` (default `ifseen`) |
| `mqtt_host`, `mqtt_port`, `mqtt_username`, `mqtt_password` | only if you don't use the Mosquitto add-on |
| `dry_run` | random probabilities, actions logged instead of run |

`/share` and `/media` are writable, e.g. for a `snapshot: /media/ifseen` action.

## Notes

- If a rules file is invalid the add-on logs the exact error and doesn't start.
- Removing or renaming a rule removes its entities. The device id is the file name, so
  renaming a file creates a new device.
- The triggering frame is published to MQTT (retained) for the camera entity. Set
  `mqtt: {host: core-mosquitto, fire_image: false}` in a file to turn that off for a private
  camera. Frames are only sent to the provider you choose.
- The add-on is built on your device from the ifseen source. Only amd64 and aarch64 are
  supported (OpenCV has no wheels for other platforms).

Full guide, including automation examples:
<https://github.com/KrishJoshi/ifseen/blob/main/docs/homeassistant.md>
