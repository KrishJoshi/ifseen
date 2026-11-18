<div align="center">

# 👁️ ifseen

**If seen (or heard), then do.**

Plain-English triggers for your screen, camera and microphone.<br>
Powered by the new *decision models*: Gemini Decision 1, Jev, Microsoft-Decision.

```bash
ifseen "a person is at the front door" --camera 0 --ntfy my-phone
```

<img src="docs/dashboard.svg" alt="ifseen dashboard watching a doorbell camera" width="900">

</div>

---

Decision models are a new kind of AI model. Instead of writing text, they read an input and
return a **calibrated probability** for each yes/no question you ask, in ~150-250 ms, with
**zero output tokens**. Gemini Decision 1 answers up to **1,000 questions about the same
image or audio clip in a single call**, billed once.

That makes something possible that used to be too slow and too expensive: *continuously*
watching a screen, camera or microphone and asking it lots of questions.

`ifseen` is the glue. You write rules in plain English, it grabs a frame (and/or a few seconds
of audio) every couple of seconds, asks every rule at once, and runs your actions when one
comes true.

```yaml
# ifseen.yaml
source: screen
every: 3s
rules:
  - name: build-failed
    when: A CI pipeline on screen has failed.
    then:
      - notify: "Build failed"
      - say: build failed
```

## Why it's nice

- **Plain English, no training.** No bounding boxes, no labelled data, no model to fine-tune.
  Ask about *anything* you'd ask a person: "the 3D print has turned into spaghetti", "someone
  asks me a question", "the pot is boiling over".
- **One call for all your rules.** 3 rules or 300, it's the same single request per frame.
- **Cheap by default.** Unchanged frames and silent audio are skipped automatically, so a
  static scene costs almost nothing. A live dashboard shows spend as you go.
- **Sees *and* hears.** With Gemini, combine a camera and a microphone in one rule set
  ("the baby is crying", "someone said my name").
- **Debounced and calm.** Thresholds, `for: N` consecutive hits, cooldowns and hysteresis, so
  you get one alert per event, not one every two seconds.
- **Bring any provider.** Gemini, Jev, Azure Microsoft-Decision, a self-hosted Jev-compatible
  server, or any OpenAI-compatible vision model, including **fully local with Ollama**.
- **Does real things.** Desktop notifications, speech, shell commands, webhooks, push
  notifications with the snapshot attached (ntfy), saving frames, or exiting so you can chain
  it in scripts.

## Install

```bash
pipx install "ifseen[all]"        # or: uv tool install "ifseen[all]"
```

Extras if you want to keep it lean: `ifseen[screen]` (mss), `ifseen[camera]` (OpenCV, also
used for video files and RTSP), `ifseen[mic]` (sounddevice). Snapshot URLs, images and WAV
files need no extras.

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
# Screen: tell me when my long-running thing finishes, then quit
ifseen "a progress bar or download on screen has completed" --say "done" --once

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
| `build-watcher` | screen | CI build/deploy failed or passed |
| `done-yet` | screen | a download, render, export or test run finished |
| `focus-guard` | screen | nudges you off doomscrolling and video binges |
| `doorbell` | camera / URL | person at the door, parcel left → phone push with photo |
| `print-failure` | camera | 3D print "spaghetti" → push alert (+ OctoPrint pause example) |
| `kitchen` | camera | water boiling, pot boiling over, smoke |
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
  name: gemini              #   gemini | jev | azure | systemone | openai | ollama | mock
  # model: gemini-decision-1
  # resolution: low         #   gemini: low | medium | high - fewer image tokens = cheaper
  # base_url: ...           #   proxies, self-hosted servers
  # api_key_env: MY_KEY_VAR

every: 2s                   # how often to look (min 100ms)
skip_unchanged: true        # don't call the API when the frame hasn't changed / audio is silent
max_skip: 60s               # ...but re-check at least this often
context: Camera above my 3D printer.   # optional text sent with every capture

rules:
  - name: spaghetti         # letters, digits, - and _
    when: The 3D print has failed and is a tangle of loose filament.
    false_means: A normal print in progress or an empty bed.   # optional clarification
    threshold: 0.85         # probability needed to count as a hit (default 0.8)
    for: 3                  # consecutive hits before firing (default 1)
    cooldown: 15m           # minimum time between fires (default 30s)
    hysteresis: 0.15        # re-arm only once probability drops below threshold - this
    then:
      - notify: "Print failed ({percent})"         # desktop notification
      - say: print failed                           # text to speech
      - shell: ./pause-printer.sh                   # runs with IFSEEN_* env vars
      - webhook: {url: https://example.com/hook, image: true}
      - ntfy: {topic: my-topic, priority: urgent}   # push to phone, photo attached
      - snapshot: ~/captures                        # save the frame
      - log: "{rule} at {time}"
      - exit                                        # stop watching
```

**Templates** in action strings: `{rule}`, `{when}`, `{prob}`, `{percent}`, `{time}`,
`{source}`, `{snapshot}`. In `shell` commands they're shell-quoted, and the same values are
also exported as `IFSEEN_RULE`, `IFSEEN_PERCENT`, `IFSEEN_SNAPSHOT`, etc.

**Writing good rules.** Decision models work best with narrow, positive statements about
what's visible or audible. Prefer "A parcel is on the doorstep" over "Is there anything
unusual?". Split complex conditions into several rules. Use `false_means` to rule out
look-alikes.

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
| `jev` | `TYPESAFE_API_KEY` | ✅ | | TypeSafe Jev 1.13+; $0.042 / 1M input tokens |
| `azure` | `AZURE_DECISION_ENDPOINT`, `AZURE_DECISION_KEY`, `AZURE_DECISION_DEPLOYMENT` | ✅ | | Microsoft-Decision-1.1 on Azure Foundry |
| `systemone` | `base_url` (+ optional `TYPESAFE_API_KEY`) | ✅ | | any self-hosted Jev-compatible `/v1/systemone` server |
| `openai` | `OPENAI_API_KEY` (+ `OPENAI_BASE_URL`), `model` | ✅ | | any OpenAI-compatible vision chat model. Not calibrated, slower |
| `ollama` | `model` | ✅ | | fully local, e.g. `--provider ollama --model gemma3` |
| `mock` | | ✅ | ✅ | what `--dry-run` uses |

With no `provider` set, ifseen picks the first one it finds a key for, in that order.

**What does it cost?** It depends on image size and how often the scene changes. A changing
scene checked every 2 s with Gemini at default resolution is on the order of tens of cents
per hour. With `resolution: low`, a longer `every`, and `skip_unchanged` doing its job on a
mostly static scene, it's typically a few cents per hour or less. The dashboard shows the
real number live.

## Run it headless / in Docker

`--json` prints one JSON event per line (`start`, `decision`, `fire`, `error`, `stop`), which
is handy for piping into `jq`, a log shipper or Home Assistant. `--plain` gives readable log
lines. Both are used automatically when stdout isn't a terminal.

```bash
docker build -t ifseen .
docker run --rm -e GEMINI_API_KEY -e NTFY_TOPIC -e DOORBELL_SNAPSHOT_URL ifseen watch doorbell
```

## Privacy

Frames and audio are sent to the provider you choose, and nowhere else. If that's a problem
for a given camera, use `--provider ollama` (or a self-hosted `systemone` server) and nothing
leaves your machine. Snapshots are only written to disk when a rule fires and you've asked
for them.

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
