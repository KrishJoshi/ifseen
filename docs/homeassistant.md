# ifseen + Home Assistant

ifseen turns plain-English rules ("a parcel has been left on the doorstep") into Home
Assistant entities. Each rules file shows up as one **device**, and each rule gets a
`binary_sensor` that's on while the rule is true, plus a probability `sensor`. Automate on
them like any other sensor.

There are two ways to run it:

- **The add-on** (Home Assistant OS / Supervised): install it from this repository, drop rules
  files in its config folder, done. MQTT is configured for you. See [The add-on](#the-add-on).
- **Anywhere else** (a server, a Pi, Docker, your laptop): `pip install 'ifseen[mqtt]'`, add an
  `mqtt:` section to a rules file and run `ifseen watch`. See [MQTT setup](#mqtt-setup).

Both need an MQTT broker that Home Assistant uses. If you don't have one, install the
**Mosquitto broker** add-on and the **MQTT** integration (Settings > Devices & services).

## MQTT setup

```bash
pip install 'ifseen[mqtt]'          # or ifseen[all], which includes it
```

```yaml
# front-door.yaml
source:
  url:
    url: http://homeassistant.local:8123/api/camera_proxy/camera.front_door
    headers:
      Authorization: Bearer ${HA_TOKEN}
every: 3s

mqtt:
  host: homeassistant.local         # your broker
  username: ifseen
  password: ${MQTT_PASSWORD}        # ${VAR}s come from the environment, keep secrets out of files
  name: Front door                  # the Home Assistant device name

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

```bash
export HA_TOKEN=... MQTT_PASSWORD=... GEMINI_API_KEY=...
ifseen watch front-door.yaml
```

The device appears under Settings > Devices & services > MQTT within a few seconds. Try it
without a decision-model key first with `ifseen watch front-door.yaml --dry-run`: probabilities
are random, but the entities, states and camera are all real, so you can build your
automations before paying for a single call.

### `mqtt:` reference

| key | default | |
|---|---|---|
| `host` | required | broker hostname or IP. Shorthand: `mqtt: core-mosquitto` or `mqtt: broker.lan:8883` |
| `port` | `1883` | |
| `username`, `password` | none | use `${VAR}` for the password |
| `tls` | off | `true`, or `{ca_certs: /path/ca.pem, certfile: ..., keyfile: ..., insecure: false}` |
| `client_id` | `ifseen-<id>-<random>` | |
| `keepalive` | `60` | seconds |
| `name` | derived from `id` | Home Assistant device name, e.g. `Front door` |
| `id` | derived | the watcher id used in topics and `unique_id`s, see below |
| `base_topic` | `ifseen` | state topics live under `<base_topic>/<id>/` |
| `discovery` | `true` | publish Home Assistant discovery configs. `false` removes any published earlier |
| `discovery_prefix` | `homeassistant` | must match the MQTT integration's discovery prefix |
| `fire_image` | `true` | publish the frame that triggered the latest fire to a camera entity |
| `frame_every` | `0` (off) | also publish the latest analysed frame at most this often, e.g. `10s` (min `1s`) |
| `pause_switch` | `true` | a switch to pause/resume watching from Home Assistant |

Per rule, `ha_device_class` sets the binary sensor's
[device class](https://www.home-assistant.io/integrations/binary_sensor/#device-class):
`occupancy`, `motion`, `presence`, `problem`, `safety`, `smoke`, `door`, `garage_door`,
`opening`, `moisture`, `sound`, ... (the full list is validated). Without one, the sensor is a
plain on/off with an eye icon.

**The watcher id** is `mqtt.id` if set, else a slug of `mqtt.name`, else the rules file name
(`front-door.yaml` -> `front-door`), else `ifseen`. It's baked into every topic and
`unique_id`, so pick it once: changing it creates a new device. Two running watchers must not
share an id.

When `mqtt:` is set, a rule without `then:` runs no actions (normally it would show a desktop
notification): Home Assistant is where you act on it. Rules can still have `then:` actions
alongside MQTT.

### Python and `ifseen serve`

```python
from ifseen import Watcher

w = Watcher(source={"camera": 0}, provider="gemini", mqtt={"host": "broker", "name": "Desk"})
w.add_rule("A person is sitting at the desk.", name="at-desk")
w.run()
```

`Watcher.from_yaml("front-door.yaml")` uses the file's `mqtt:` section and its file name as
the default id; `Watcher(name=...)` is the default id otherwise. `w.pause()` / `w.resume()`
and `w.state()["paused"]` match the Home Assistant switch.

`ifseen serve a.yaml b.yaml` gives each preloaded file with an `mqtt:` section its own MQTT
connection and device; the default id is the watcher id (the file name). Configs sent over the
HTTP API can't contain `mqtt:` (it would stream your camera frames to any broker the client
names) unless the server runs with `--allow-custom-endpoints`.

The one-liner (`ifseen "condition" ...`) has no MQTT option; write a rules file.

## Entities

For a device named **Front door** (id `front-door`) with a rule `person-at-door`:

| entity | example id | |
|---|---|---|
| binary sensor per rule | `binary_sensor.front_door_person_at_door` | on from the moment the rule fires until it re-arms |
| sensor per rule | `sensor.front_door_person_at_door_probability` | latest probability in %, attributes below |
| event | `event.front_door_trigger` | fires once per rule fire; `event_type` is the rule name |
| camera | `camera.front_door_last_trigger` | the frame that triggered the latest fire |
| camera | `camera.front_door_latest_frame` | only with `frame_every` |
| switch | `switch.front_door_watching` | off = paused: no captures, no model calls, no cost |
| sensor | `sensor.front_door_status` | `watching` / `paused` / `stopped` / `error`, stats as attributes |
| sensor | `sensor.front_door_cost_per_hour` | `$/h` at the current rate |
| sensor | `sensor.front_door_model_calls` | calls this run |

Every entity has an availability topic: when ifseen stops (or crashes, or loses its connection:
the broker publishes its last will) everything shows *unavailable* instead of a stale state.

Probability sensor attributes: `probability`, `active`, `threshold` (%), `streak`, `for`,
`fires`, `last_fired` (ISO time, this run), `when` (the rule text).

### When is the binary sensor on?

It follows ifseen's own trigger logic exactly, so it means "this rule fired and hasn't
cleared yet":

- **On** when the rule fires: probability at or above `threshold` for `for` consecutive checks,
  outside its `cooldown`.
- **Off** when it re-arms: the probability drops below `threshold - hysteresis` (default 0.15,
  never below half the threshold). A probability hovering just under the threshold doesn't
  flap it off and on.
- `cooldown` only delays the *next* fire, so after a re-arm the sensor can stay off for a while
  even though the condition is true again. Use a short cooldown (`cooldown: 0`) for rules that
  model a state ("garage door open"), a longer one for events you want once ("parcel left").
- Pausing keeps the sensor where it was. Restarting ifseen starts every rule off.

### Topics

Everything lives under `<base_topic>/<id>/` (default `ifseen/front-door/`); retained unless
noted.

| topic | payload |
|---|---|
| `availability` | `online` / `offline` (last will) |
| `state` | `{"status", "source", "provider", "calls", "skipped", "errors", "input_tokens", "cost_usd", "cost_per_hour"}`, at most every 30 s unless the status changes |
| `rule/<rule>/active` | `ON` / `OFF` |
| `rule/<rule>/probability` | the JSON attributes above, published when they change |
| `event` | `{"event_type": "<rule>", "probability": 93.1, "time": "..."}`, not retained |
| `camera/fire` | JPEG of the triggering frame |
| `camera/frame` | JPEG, not retained, only with `frame_every` |
| `watching` | `ON` / `OFF` |
| `watching/set` | send `ON` / `OFF` to resume / pause |

Discovery configs go to `<discovery_prefix>/<component>/ifseen_<id>/<object>/config`, with
`unique_id` `ifseen_<id>_<object>` (e.g. `ifseen_front-door_person-at-door_active`), so entity
ids, names and areas you set in Home Assistant survive restarts. On connect ifseen clears
any retained discovery config and rule state under its own id that the current config no
longer has, so **removing or renaming a rule removes its entities**. Turning `fire_image`,
`frame_every` or `pause_switch` off does the same for those entities.

If the broker goes away, watching carries on and ifseen reconnects with backoff (1-60 s). After
reconnecting it republishes availability, discovery and every current state. MQTT errors are
logged and never stop the watch loop.

## Using Home Assistant cameras as the source

Any camera entity can be the source through HA's `camera_proxy` endpoint, which returns the
current frame as a JPEG:

```yaml
source:
  url:
    url: http://homeassistant.local:8123/api/camera_proxy/camera.front_door
    headers:
      Authorization: Bearer ${HA_TOKEN}
```

Create the token under your user profile > Security > Long-lived access tokens, and pass it as
an environment variable (`export HA_TOKEN=...`), never in the file.

Inside the add-on you don't need a token: the Supervisor proxies the API for you.

```yaml
source:
  url:
    url: http://supervisor/core/api/camera_proxy/camera.front_door
    headers:
      Authorization: Bearer ${SUPERVISOR_TOKEN}
```

Tips:

- `camera_proxy` returns the camera's current still. Some integrations only refresh it every
  few seconds, so `every:` below that just re-reads the same frame (skipped for free as
  unchanged).
- If your camera has an RTSP stream, `source: {camera: "rtsp://user:pass@cam/stream"}` reads it
  directly at full rate (needs `ifseen[camera]`, included in the add-on).
- Frigate users can point at `http://frigate:5000/api/<camera>/latest.jpg` instead.

## Example rules

```yaml
# doorbell.yaml
source: {url: {url: http://supervisor/core/api/camera_proxy/camera.doorbell, headers: {Authorization: "Bearer ${SUPERVISOR_TOKEN}"}}}
every: 3s
rules:
  - name: person-at-door
    when: A person is standing at the front door.
    false_means: The doorstep is empty, or someone is only walking past on the street.
    threshold: 0.85
    for: 2
    ha_device_class: occupancy
  - name: parcel-left
    when: A parcel, package or delivery bag has been left on the doorstep.
    threshold: 0.85
    for: 3
    cooldown: 30m
```

```yaml
# garage.yaml - a state, so no cooldown: the sensor tracks the door
source: {url: {url: http://supervisor/core/api/camera_proxy/camera.garage, headers: {Authorization: "Bearer ${SUPERVISOR_TOKEN}"}}}
every: 30s
rules:
  - name: garage-open
    when: The garage door is open.
    false_means: The garage door is fully closed.
    threshold: 0.8
    for: 2
    cooldown: 0
    ha_device_class: garage_door
  - name: car-in-garage
    when: A car is parked inside the garage.
    cooldown: 0
    ha_device_class: presence
```

```yaml
# pets.yaml
source: {camera: "rtsp://user:${CAM_PASSWORD}@192.168.1.40/stream2"}
every: 5s
mqtt: {host: core-mosquitto, name: Living room pets, frame_every: 30s}
rules:
  - name: dog-on-sofa
    when: A dog is lying or sitting on the sofa.
    threshold: 0.8
    for: 2
    ha_device_class: occupancy
  - name: cat-on-counter
    when: A cat is on the kitchen counter.
    threshold: 0.8
    ha_device_class: problem
```

`ifseen test doorbell.yaml --image doorstep.jpg` prints each rule's probability for a single
photo, which is the quickest way to pick thresholds.

## Automations

Notify with the snapshot when a parcel arrives:

```yaml
alias: Parcel delivered
triggers:
  - trigger: state
    entity_id: binary_sensor.front_door_parcel_left
    from: "off"
    to: "on"
actions:
  - action: notify.mobile_app_my_phone
    data:
      title: Parcel delivered
      message: "{{ state_attr('sensor.front_door_parcel_left_probability', 'probability') }}% sure"
      data:
        image: /api/camera_proxy/camera.front_door_last_trigger
```

Close the garage if it's been open for 10 minutes after dark:

```yaml
alias: Garage left open
triggers:
  - trigger: state
    entity_id: binary_sensor.garage_garage_open
    to: "on"
    for: "00:10:00"
conditions:
  - condition: sun
    after: sunset
actions:
  - action: cover.close_cover
    target:
      entity_id: cover.garage_door
```

React to every fire, including repeat fires of the same rule, with the event entity:

```yaml
alias: Any ifseen trigger on the front door
triggers:
  - trigger: state
    entity_id: event.front_door_trigger
actions:
  - action: logbook.log
    data:
      name: ifseen
      message: "{{ trigger.to_state.attributes.event_type }} fired"
```

Only watch (and pay) while nobody's home:

```yaml
alias: ifseen only when away
triggers:
  - trigger: state
    entity_id: group.family
actions:
  - action: "switch.turn_{{ 'on' if is_state('group.family', 'not_home') else 'off' }}"
    target:
      entity_id: switch.front_door_watching
```

## The add-on

The repository is also a Home Assistant add-on repository (`repository.yaml` at the root, the
add-on in `homeassistant/ifseen/`).

1. Settings > Add-ons > Add-on store > ⋮ > **Repositories**, add
   `https://github.com/KrishJoshi/ifseen`.
2. Install **ifseen**. It's built on your device (a few minutes; amd64 and aarch64 only, because
   OpenCV has no wheels for other platforms).
3. Install the **Mosquitto broker** add-on if you don't have a broker. ifseen picks it up
   automatically through the Supervisor, no MQTT settings needed.
4. In the add-on's **Configuration** tab, choose a provider and paste its API key (stored as a
   password field). `mock` / **Dry run** need no key.
5. Start it once. With no rules it writes `front-door.yaml.example` to its config folder
   (`/addon_configs/xxxxxxxx_ifseen/` on the host, e.g. through the Samba or File editor
   add-ons) and stops. Rename it to `front-door.yaml`, edit, and start again.

Every `*.yaml` in that folder is one watcher and one device; the file name is the id. You can
point **Rules location** at another folder or file instead (your HA config is mounted
read-only at `/homeassistant`, `/share` and `/media` are writable, e.g. for `snapshot:`
actions), or paste a whole rules file into **Inline rules**. A file without an `mqtt:` section
gets the add-on's broker; a file without a `provider` gets the add-on's provider. If one
file is invalid the add-on logs the exact problem and doesn't start.

The add-on runs `ifseen serve` with all the files, so the HTTP API is available inside the
container on 127.0.0.1:8899 (not exposed).

## Privacy

- Frames go to the decision provider you pick and nowhere else. For cameras you don't want to
  leave the house, use `ollama` or a self-hosted `systemone` server.
- MQTT payloads are rule states, probabilities and, unless you turn them off, JPEGs: the
  triggering frame (`fire_image`, retained on the broker so the camera entity has a picture
  after a restart) and optionally a frame every `frame_every`. Anyone who can subscribe to
  `ifseen/#` on your broker can see them. Use broker credentials/ACLs, and set
  `fire_image: false` for cameras covering private spaces.
- `frame_every` is off by default: a frame every few seconds is a lot of traffic and effectively
  a second video feed.
- Passwords and tokens should be `${VAR}` references. ifseen never logs them, and they're never
  part of `state()` or the HTTP API.
