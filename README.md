<div align="center">

# 👁️ ifseen

**If seen (or heard), then do.**

Turn anything your screen, camera or mic can pick up into an event.<br>
**No API. No integration. No model training.** Just a sentence.<br>
Powered by the new *decision models*: Gemini Decision 1, Jev, Microsoft-Decision.

```bash
ifseen "a pan is cooking on a lit hob and nobody is in the kitchen" --camera 0 --ntfy my-phone
```

<img src="docs/media/hero.gif" alt="ifseen watching a kitchen camera: the cook walks out leaving the hob on and the hob-unattended rule fires at 89%" width="900">

<sub>AI-generated scene · real ifseen output (Gemini Decision 1) · <a href="https://krishj.com/ifseen/">website</a></sub>

<img src="docs/dashboard.svg" alt="ifseen live dashboard" width="900">

</div>

---

Decision models are a new kind of AI model. Instead of writing text, they read an input and
return a **calibrated probability** for each yes/no question you ask, typically in under a
second, with **zero output tokens**. Gemini Decision 1 answers up to **1,000 questions about the same
image or audio clip in a single call**, billed once.

That makes something possible that used to be too slow and too expensive: *continuously*
watching a screen, camera or microphone and asking it lots of questions.

`ifseen` is the glue. You write rules in plain English, it grabs a frame (and/or a few seconds
of audio) every couple of seconds, asks every rule at once, and runs your actions when one
comes true.

```yaml
# ifseen.yaml - a webcam pointed at a washing machine that has no app
source: {camera: 0}
every: 30s
rules:
  - name: cycle-finished
    when: The washing machine's display shows the cycle has finished, such as "End" or "0:00".
    false_means: The display shows time remaining and the cycle is still running.
    for: 2
    then:
      - ntfy: my-laundry-topic
      - say: the washing is done
```

## What it's for: things with no API

If a person can see it or hear it, ifseen can turn it into an event. Every number below is a
real `ifseen test` output (rule true / near-identical frame where it's false) on
[AI-generated scenes](docs/media/README.md):

| use case | the old way | ifseen rule | Gemini Decision 1 | TypeSafe Jev |
|---|---|---|---|---|
| Hob left on, nobody in the kitchen | heat sensor + presence sensor + glue logic | "A pan is cooking on a lit hob, with flame or steam, and nobody is in the kitchen." | 94.4% / 3.2% | 96% / 2% |
| Dumb washing machine finished | replace the machine, or smart-plug power guessing | "The washing machine's display shows the cycle has finished…" | 95.7% / 5.8% | 98% / 2% |
| No hi-vis vest in the loading bay | label thousands of images, train a detector, retrain per site | "A person in the loading bay is wearing ordinary clothes with no high-visibility vest." | 91.9% / 4.7% | 98% / 4% |
| Empty shelf, restock needed | shelf-scanning robots or custom CV | "Part of a shelf is empty, with a visible gap where products should be." | 94.3% / 26.6% | 97% / 33% |
| Alarm on a legacy HMI with no API | RPA / screen-scraping bots, or someone watching | "The control screen shows an active alarm, such as a red alarm banner or a tripped pump." | 97.0% / 1.4% | 99% / 3% |

## Why it's nice

- **Plain English, no training.** No bounding boxes, no labelled data, no model to fine-tune.
  Ask about *anything* you'd ask a person: "someone in the loading bay has no hi-vis vest",
  "someone asks me a question", "the pot is boiling over".
- **One call for all your rules.** 3 rules or 300, it's the same single request per frame.
- **Cheap by default.** Unchanged frames and silent audio are skipped automatically, so a
  static scene costs almost nothing. A live dashboard shows spend as you go.
- **Sees *and* hears.** With Gemini, combine a camera and a microphone in one rule set
  ("the baby is crying", "someone said my name").
- **Debounced and calm.** Thresholds, `for: N` consecutive hits, cooldowns and hysteresis, so
  you get one alert per event, not one every two seconds.
- **Bring any provider.** Gemini, Jev, Azure Microsoft-Decision, a self-hosted Jev-compatible
  server, or any OpenAI-compatible vision model, including **fully local with Ollama**, or
  free on-device SigLIP (`--provider local`), alone or as a cheap first check.
- **Does real things.** Desktop notifications, speech, shell commands, webhooks, push
  notifications with the snapshot attached (ntfy), saving frames, or exiting so you can chain
  it in scripts.

## Install

| platform | install |
|---|---|
| **macOS** | `brew install krishjoshi/tap/ifseen` or `curl -fsSL https://krishj.com/ifseen/install.sh \| sh` |
| **Windows** | `irm https://krishj.com/ifseen/install.ps1 \| iex`, or `scoop bucket add krishjoshi https://github.com/KrishJoshi/scoop-bucket` then `scoop install ifseen`, or download the `.exe` from [Releases](https://github.com/KrishJoshi/ifseen/releases/latest) |
| **Linux** | `curl -fsSL https://krishj.com/ifseen/install.sh \| sh` (x86_64 / arm64), or `brew` / `pipx` |
| **Python** (any OS) | `pipx install "ifseen[all]"` or `uv tool install "ifseen[all]"` |
| **Docker** | Docker Compose quick start in [Docker](#run-it-headless--in-docker), or `docker run --rm -e GEMINI_API_KEY ghcr.io/krishjoshi/ifseen ...` (amd64 / arm64) |
| **Home Assistant** | [![Add the ifseen add-on repository to Home Assistant](https://my.home-assistant.io/badges/supervisor_add_addon_repository.svg)](https://my.home-assistant.io/redirect/supervisor_add_addon_repository/?repository_url=https%3A%2F%2Fgithub.com%2FKrishJoshi%2Fifseen) then install the **ifseen** add-on (see [Home Assistant](#home-assistant)) |
| **JS / TS** | `npm install ifseen` (a client for `ifseen serve`; see [below](#use-it-from-javascript--typescript)) |

The Homebrew, Scoop, install-script and `.exe` options are standalone binaries: no Python
needed, with screen, camera, mic and MQTT built in. They don't include the `local` (SigLIP)
provider, which needs torch: use `pipx` / `uv` for that. The install script verifies the
SHA-256 against the release's `SHA256SUMS`, installs to `~/.local/bin` without sudo
(`IFSEEN_INSTALL_DIR` and `IFSEEN_VERSION` change the folder and version) and clears the macOS
quarantine flag. The binaries aren't signed yet: if you download one by hand on macOS, run
`xattr -d com.apple.quarantine ./ifseen`; on Windows, SmartScreen may need **More info → Run
anyway**. On Linux the mic needs the system PortAudio library (`sudo apt install libportaudio2`).

With pip, pipx or uv, pick extras to keep it lean: `ifseen[screen]` (mss), `ifseen[camera]` (OpenCV, also
used for video files and RTSP), `ifseen[mic]` (sounddevice), `ifseen[mqtt]` (paho-mqtt, for
[Home Assistant](#home-assistant)). Snapshot URLs, images and WAV files need no extras. `ifseen[local]` (torch + transformers) adds the free offline provider;
it's big, so it isn't part of `all`.

Then get a key. The easiest is a **free Gemini API key** from
[Google AI Studio](https://aistudio.google.com/apikey):

```bash
export GEMINI_API_KEY=...
ifseen doctor                     # checks keys, dependencies and capture permissions
```

No key yet? Everything works offline with `--dry-run` (random probabilities, actions are
printed instead of run).

## 30-second tour

```bash
# Screen: a legacy app with no API raises an alarm (works inside Citrix/RDP windows too)
ifseen "the control screen shows a red alarm banner" --screen 1 --ntfy plant-alerts --for 2

# Webcam: kettle timer that actually looks
ifseen "a pot of water is at a rolling boil" --camera 0 --say "water's boiling"

# Any IP camera / Frigate / Home Assistant snapshot URL, pushed to your phone with the photo
ifseen "a parcel has been left on the doorstep" --url http://frigate.local/api/door/latest.jpg \
       --ntfy my-secret-topic --for 2

# Microphone (Gemini): zone out on calls safely
ifseen "someone says the name Krish or asks Krish a question" --mic --notify --provider gemini

# Several conditions at once, run a script when any fires
ifseen "the dog is on the sofa" "the cat is on the counter" --camera 0 --then ./yell.sh
```

## Recipes

Ready-made rule files. Run one directly, or copy it and make it yours:

```bash
ifseen recipes                    # list them
ifseen watch doorbell             # run one
ifseen init doorbell              # write ./ifseen.yaml to customise
```

| recipe | source | what it does |
|---|---|---|
| `appliance-done` | camera | a dumb washer/dishwasher display shows End / 0:00 → push + speech |
| `warehouse-safety` | camera | someone in the loading bay without a hi-vis vest, person near a forklift → webhook with photo |
| `shelf-restock` | URL | a visible gap on a shelf → webhook with photo |
| `legacy-screen-alarm` | screen | an HMI / SCADA / vendor app shows an alarm → urgent push |
| `focus-guard` | screen | nudges you off doomscrolling and video binges |
| `doorbell` | camera / URL | person at the door, parcel left → phone push with photo |
| `print-failure` | camera | 3D print "spaghetti" → push alert (+ OctoPrint pause example) |
| `kitchen` | camera | water boiling, pot boiling over, smoke, hob left on with nobody there |
| `pet-patrol` | camera | dog on the sofa, cat on the counter |
| `meeting-radar` | mic | your name, a question for you, an action item for you |
| `baby-monitor` | camera + mic | crying, standing in the cot, face covered |

Recipes read secrets and per-machine settings from environment variables
(`${NTFY_TOPIC}`, `${MY_NAME:-Alex}`, ...), so you can share rule files safely.

## Rules file reference

```yaml
source:                     # one visual source and/or a mic
  screen: 1                 #   monitor number (0 = all), or {monitor: 1, region: [x, y, w, h]}
  # camera: 0               #   webcam index, or rtsp://user:pass@cam/stream
  # url: http://cam/snapshot.jpg   (or {url: ..., headers: {...}})
  # file: clip.mp4          #   image, .wav or video; {path: ..., realtime: false, loop: true}
  # mic: {seconds: 5}       #   last N seconds of audio each tick (Gemini only)

provider:                   # optional - auto-detected from env vars
  name: gemini              #   gemini | jev | azure | systemone | openai | ollama | local | mock
  # model: gemini-decision-1
  # resolution: low         #   gemini: low | medium | high - fewer image tokens = cheaper
  # base_url: ...           #   proxies, self-hosted servers
  # api_key_env: MY_KEY_VAR

every: 2s                   # how often to look (min 100ms)
skip_unchanged: true        # don't call the API when the frame hasn't changed / audio is silent
change_threshold: 0.25      # % of pixels that must change for a frame to count as changed
max_skip: 60s               # ...but re-check at least this often
context: Camera above my 3D printer.   # optional text sent with every capture
mqtt: core-mosquitto        # optional: publish to Home Assistant, see docs/homeassistant.md

prefilter:                  # optional cheap first check, see "Cheap first check" below
  provider: local           #   any provider; required, never auto-detected
  when: a photo of a 3D printer.
  threshold: 0.05           #   main provider is only called at or above this (default 0.05)

rules:
  - name: spaghetti         # letters, digits, - and _
    when: The 3D print has failed and is a tangle of loose filament.
    false_means: A normal print in progress or an empty bed.   # optional clarification
    threshold: 0.85         # probability needed to count as a hit (default 0.8)
    for: 3                  # consecutive hits before firing (default 1)
    cooldown: 15m           # minimum time between fires (default 30s)
    hysteresis: 0.15        # re-arm only once probability drops below threshold - this
    ha_device_class: problem  # optional, Home Assistant binary_sensor device class (mqtt)
    then:
      - notify: "Print failed ({percent})"         # desktop notification
      - say: print failed                           # text to speech
      - shell: ./pause-printer.sh "$IFSEEN_SNAPSHOT" # gets IFSEEN_* env vars
      - webhook: {url: https://example.com/hook, image: true}
      - ntfy: {topic: my-topic, priority: urgent}   # push to phone, photo attached
      - snapshot: ~/captures                        # save the frame
      - log: "{rule} at {time}"
      - exit                                        # stop watching
```

**Templates** in `notify`, `say`, `log`, `ntfy` and `webhook` strings: `{rule}`, `{when}`,
`{prob}`, `{percent}`, `{time}`, `{source}`, `{snapshot}`. **Shell commands are never
templated**, so nothing from a file name, URL or rule can inject shell syntax. Instead they
get the same values as environment variables: `$IFSEEN_RULE`, `$IFSEEN_PERCENT`,
`$IFSEEN_SNAPSHOT` (path to the triggering frame), etc. On Windows, shell actions run in
`cmd`, so use `%IFSEEN_RULE%`.

**Writing good rules.** Decision models work best with narrow, positive statements about
what's visible or audible. Prefer "A parcel is on the doorstep" over "Is there anything
unusual?". Split complex conditions into several rules. Use `false_means` to rule out
look-alikes.

## Cheap first check (cascade)

A `prefilter` asks one cheap question every tick and only calls your main provider when it
passes. Pair the free, offline `local` provider (good at "is there a person/dog/car?") with a
decision model for the harder rules:

```yaml
source: {camera: 0}
provider: gemini
prefilter:
  provider: local
  when: a photo of a dog.
  threshold: 0.05
rules:
  - name: dog-on-sofa
    when: A dog is lying on the sofa.
```

When the prefilter is below its threshold, every rule reads 0% (it fails closed, so nothing
fires) and the tick counts as skipped with reason `prefilter`. The dashboard footer shows
the latest prefilter score and how many ticks it saved, and `--json` decision events carry
`prefilter` (its probability) and `skipped: "prefilter"`. Unchanged-frame skipping still runs
first, so a static scene costs neither call. `ifseen test` prints whether the prefilter would
have let the main provider look. One-liners can use `--prefilter "A dog is visible."`.

Keep the prefilter question broad and its threshold low: a missed prefilter means a missed
event, while a false pass only costs one normal call. That's why the default is 0.05: with
`local`, "a photo of a dog." scored at least 0.13 on photos with a dog and at most 0.02 without
in our benchmark, so the useful cut-off sits far below 50%. Check yours with `ifseen test`.

## Tuning thresholds

`ifseen test` asks every rule once and prints the probabilities, so you can pick thresholds
from real examples:

```bash
ifseen test doorbell --image doorstep.jpg
```

```
image doorstep.jpg → gemini (gemini-decision-1)
┏━━━━━━━━━━━━━━━━┳━━━━━━━━━━━━━┳━━━━━━━━━━━┳━━━━━━━━━━━━┓
┃ rule           ┃ probability ┃ threshold ┃ would fire ┃
┡━━━━━━━━━━━━━━━━╇━━━━━━━━━━━━━╇━━━━━━━━━━━╇━━━━━━━━━━━━┩
│ person-at-door │        3.1% │       80% │ no         │
│ parcel-left    │       96.4% │       85% │ yes        │
└────────────────┴─────────────┴───────────┴────────────┘
```

## Providers

| provider | env vars | sees | hears | notes |
|---|---|:-:|:-:|---|
| `gemini` | `GEMINI_API_KEY` | ✅ | ✅ | Gemini Decision 1. Free tier; $0.10 / 1M input tokens |
| `jev` | `TYPESAFE_API_KEY` | ✅ | | TypeSafe Jev 1.13+; $0.042 / 1M input tokens. Live-tested: 100% on the hard-rules images, ~180 ms |
| `azure` | `AZURE_DECISION_ENDPOINT`, `AZURE_DECISION_KEY`, `AZURE_DECISION_DEPLOYMENT` | ✅ | | Microsoft-Decision-1.1 on Azure Foundry |
| `systemone` | `base_url` (+ optional `TYPESAFE_API_KEY`) | ✅ | | any self-hosted Jev-compatible `/v1/systemone` server |
| `openai` | `OPENAI_API_KEY` (+ `OPENAI_BASE_URL`), `model` | ✅ | | any OpenAI-compatible vision chat model. Not calibrated, slower |
| `ollama` | `model` | ✅ | | fully local, e.g. `--provider ollama --model gemma3` |
| `local` | none (`pip install 'ifseen[local]'`) | ✅ | | free, offline SigLIP zero-shot. Fast, but weak on screen text and states; see below |
| `mock` | | ✅ | ✅ | what `--dry-run` uses |

With no `provider` set, ifseen picks the first one it finds a key for, in that order
(`local` is never picked automatically).

### Free & offline: `--provider local`

```bash
pip install 'ifseen[local]'       # torch + transformers, ~1 GB with the model
ifseen "a photo of a dog on a sofa" --camera 0 --provider local --threshold 0.5
```

`local` runs a zero-shot image-text model on your machine (default
`google/siglip-base-patch16-224`, or any CLIP/SigLIP id as `model`). It uses Apple MPS or
CUDA when available, takes about 20 ms per frame on an M-series Mac after a one-off model
load and download, costs nothing and sends nothing anywhere. It can't hear.

How it scores a rule:

- **No `false_means`:** SigLIP's own image-caption match score, shifted (`sigmoid(logit + 3)`)
  because raw SigLIP scores for true captions mostly sit around 1-30%. Good for "is X there /
  is X on Y" rules.
- **With `false_means`:** a two-way choice between `when` and `false_means`. Use this for
  states whose "no" looks like the "yes": `when: The door is open.` +
  `false_means: The door is closed.`

The numbers aren't calibrated like a decision model's: always pick thresholds with
`ifseen test --provider local`, and phrase rules like captions ("a photo of a dog on a
sofa"). Long rules are cut at 64 tokens, and `context` and `true_means` are ignored. In
[our benchmark](benchmarks/hard-rules-results.md) it matched Gemini Decision 1 on objects
and simple spatial rules, but read CI status off a screenshot barely better than chance
and missed most boiling pots. It works best as a free [prefilter](#cheap-first-check-cascade) in
front of a decision model.

**What does it cost?** Measured with Gemini Decision 1: a 1280×800 frame is about 1,350
input tokens ($0.000135), or about 520 tokens ($0.00005) with `resolution: low`, which was
just as accurate in testing, even for reading text on a CI page. A 5-second audio clip is
about 400 tokens. So a scene that changes on *every* 2-second check costs roughly $0.24/hour
(about $0.09/hour at low resolution). Unchanged frames and silent audio are skipped, so a mostly
static camera or screen costs a small fraction of that. The dashboard shows the real number.

## Use it from Python

```python
from ifseen import Watcher, check, FireEvent

# One-shot: an image path, bytes or PIL image (and/or audio=... WAV)
probs = check("door.jpg", ["A parcel is on the doorstep.", "A person is visible."], provider="gemini")
# {"a-parcel-is-on-the-doorstep": 0.96, "a-person-is-visible": 0.03}
probs = check("door.jpg", {"parcel": "A parcel is on the doorstep."})   # your own names

# Long-running: same shapes as the YAML file
w = Watcher(source={"camera": 0}, provider="gemini", every="2s")
# keys come from env vars (GEMINI_API_KEY, ...) or explicitly: Watcher(..., provider="jev", api_key="...")

@w.when("A person is at the front door.", threshold=0.85, for_=2, cooldown="1m", name="person")
def person(event: FireEvent) -> None:          # async def works too
    print(event.name, event.probability, len(event.jpeg or b""))

w.add_rule("A parcel is on the doorstep.", then=[{"ntfy": "my-topic"}])  # YAML actions still work
w.on_decision(lambda e: print(e["probs"]))      # the event stream: start/decision/fire/error/stop/log
w.on_error(lambda e: print("error:", e["message"]))

w.run()                     # blocks; Ctrl+C stops cleanly
# await w.run_async()       # from asyncio: async callbacks run on your event loop
# w.start(); ...; w.state(); w.snapshot(); w.stop()   # background thread
```

`Watcher.from_yaml("rules.yaml")` and `Watcher.from_config({...})` load existing rule files;
attach a callback to one of their rules with `@w.on("rule-name")`. A rule with a callback and
no `then:` runs only the callback (no desktop notification). Callback exceptions are logged
and reported as `error` events, never stopping the watcher. `w.state()` returns each rule's
probability, streak, armed flag and fire count plus call/skip/cost stats. Pass
`dry_run=True` to use the mock provider without a key.

## Use it from JavaScript / TypeScript

`npm install ifseen` - zero dependencies, works in Node 18+, Bun, Deno and browsers.

```ts
import { check, IfseenClient } from "ifseen";

// one-shot, straight to the decision API (server-side: keeps your key private)
const probs = await check("door.jpg", ["A parcel is on the doorstep."], {
  provider: "gemini", apiKey: process.env.GEMINI_API_KEY,
});

// live watchers via a local `ifseen serve`
const client = new IfseenClient({ baseUrl: "http://127.0.0.1:8899" });
client.on("fire", (e) => console.log(`${e.rule} fired at ${e.probability}`));
```

Full reference: [`js/README.md`](js/README.md).

## HTTP API (`ifseen serve`)

A small local server for other languages and home-automation hubs: one-shot checks,
watchers you create over HTTP, a live Server-Sent Events stream and the latest frame as a
JPEG. Standard library only, no extra dependencies.

```bash
ifseen serve                        # http://127.0.0.1:8899
ifseen serve doorbell               # also start a recipe / rules file

curl -s localhost:8899/v1/check -H 'Content-Type: application/json' \
  -d "{\"image_base64\": \"$(base64 < door.jpg | tr -d '\n')\", \"rules\": [\"A parcel is on the doorstep.\"]}"
curl -N localhost:8899/v1/events    # start / decision / fire / error / stop, per watcher
```

| endpoint | |
|---|---|
| `GET /v1/health` | version, usable providers |
| `POST /v1/check` | one-shot probabilities for an image / audio clip |
| `GET` / `POST /v1/watchers` | list / create (body = the rules-file config as JSON) |
| `GET` / `DELETE /v1/watchers/{id}` | state / remove |
| `POST /v1/watchers/{id}/start` · `/stop` | |
| `GET /v1/watchers/{id}/snapshot` | latest frame (JPEG) |
| `GET /v1/events[?watcher=id&types=fire,error]` | SSE event stream |

**Security.** It listens on 127.0.0.1 only and checks the `Host` header, so web pages can't
reach it. To listen on your LAN you must set a token (`--token` or `IFSEEN_TOKEN`, sent as
`Authorization: Bearer ...`); it refuses to start otherwise. Configs sent over HTTP can't use
`shell` actions (that would be remote code execution) unless you pass `--allow-shell`, can't
point a provider at another `base_url` or `api_key_env` (that could leak your API keys) unless
you pass `--allow-custom-endpoints`, and don't get `${VAR}` expansion. Rule files passed on
the command line are trusted as usual. Bodies are capped at 25 MB. Full reference, including
request/response and event schemas: [docs/api.md](docs/api.md).

## Home Assistant

Add an `mqtt:` section and every rule shows up in Home Assistant through MQTT discovery: one
device per rules file, a binary sensor per rule (on while it's fired, off once it clears), a
probability sensor, a trigger event, a camera with the frame that fired and a switch to pause
watching.

```yaml
source:
  url:
    url: http://homeassistant.local:8123/api/camera_proxy/camera.front_door
    headers: {Authorization: "Bearer ${HA_TOKEN}"}
mqtt: {host: homeassistant.local, username: ifseen, password: "${MQTT_PASSWORD}", name: Front door}
rules:
  - name: parcel-left
    when: A parcel has been left on the doorstep.
    ha_device_class: occupancy
```

`pip install 'ifseen[mqtt]'` (or any of the binaries above) and `ifseen watch front-door.yaml`.
On Home Assistant OS, this repo is also an **add-on repository**:
[add it](https://my.home-assistant.io/redirect/supervisor_add_addon_repository/?repository_url=https%3A%2F%2Fgithub.com%2FKrishJoshi%2Fifseen)
(or paste `https://github.com/KrishJoshi/ifseen` under Settings > Add-ons > Add-on store > ⋮ >
Repositories), install the add-on (prebuilt images for amd64 and aarch64), drop rules files in
the add-on's folder, and MQTT is configured for you. Full guide, with automation examples:
[docs/homeassistant.md](docs/homeassistant.md).

## Run it headless / in Docker

`--json` prints one JSON event per line (`start`, `decision`, `fire`, `error`, `stop`), which
is handy for piping into `jq` or a log shipper (for Home Assistant, use [MQTT](#home-assistant)). `--plain` gives readable log
lines. Both are used automatically when stdout isn't a terminal.

For an always-on watcher (a home server, NAS or Raspberry Pi 4/5), use Docker Compose:

```bash
mkdir ifseen && cd ifseen
curl -fsSLO https://raw.githubusercontent.com/KrishJoshi/ifseen/main/docker/compose.yaml
curl -fsSL https://raw.githubusercontent.com/KrishJoshi/ifseen/main/docker/.env.example -o .env   # set GEMINI_API_KEY and DOORBELL_SNAPSHOT_URL
mkdir rules && curl -fsSL https://raw.githubusercontent.com/KrishJoshi/ifseen/main/docker/rules/doorbell.yaml -o rules/doorbell.yaml
docker compose up -d && docker compose logs -f
```

Every `rules/*.yaml` becomes a watcher (`ifseen serve` over all of them). Upgrade with
`docker compose pull && docker compose up -d`. Full guide: [docs/docker.md](docs/docker.md).

One-off, without Compose:

```bash
docker run --rm -e GEMINI_API_KEY -e NTFY_TOPIC -e DOORBELL_SNAPSHOT_URL \
  ghcr.io/krishjoshi/ifseen watch doorbell
```

The image (`ghcr.io/krishjoshi/ifseen:latest` or `:<version>`, linux/amd64 and linux/arm64)
has the camera and MQTT extras. Cameras work through RTSP or a snapshot URL (e.g. Home
Assistant's `camera_proxy`), and mounted files work too, but there's no screen or mic inside a
container. To build it from source instead: `docker build -t ifseen .`

## Privacy

Frames and audio are sent to the provider you choose, and nowhere else. If that's a problem for
a given camera, use `--provider local` or `--provider ollama` (or a self-hosted `systemone`
server) and nothing leaves your machine. Snapshots are only written to disk when a rule fires
and you've asked for them.

macOS asks for **Screen Recording** permission for your terminal the first time you capture
the screen, and on recent versions periodically re-confirms it. `ifseen doctor` checks
capture is working.

## Development

```bash
git clone https://github.com/KrishJoshi/ifseen && cd ifseen
uv venv && uv pip install -e ".[dev]"
pytest                          # includes end-to-end tests against a local fake decision server
ruff check src tests
python tests/fake_server.py     # run the fake server yourself (key: test-key)
```

The fake server speaks the Gemini Decisions, System One and OpenAI chat wire formats and
answers colour questions by actually looking at the pixels, so the whole pipeline (capture →
encode → HTTP → state machine → actions) is tested without an API key.

## License

MIT
