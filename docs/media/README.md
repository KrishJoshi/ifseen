# Demo media

> **AI-generated scenes, real ifseen outputs.** Every photo and video here was generated with
> Google models on Vertex AI. None of it is real footage. Every probability, token count,
> latency and FIRED moment shown on top of it is a real, unedited output from
> `ifseen` (`--provider gemini`, Gemini Decision 1), recorded on 2026-11-19. Raw outputs are in
> [`data/`](data/), rule files in [`rules/`](rules/).

## Models

| what | model | settings |
|---|---|---|
| stills | `gemini-2.5-flash-image` (Nano Banana) on Vertex AI, `global` | 16:9, 1344×768. The "false" image of each pair is an edit of the "true" one, so only the thing the rule is about changes |
| clips | `veo-3.1-lite-generate-001` on Vertex AI, `us-central1` | image-to-video from a still, 6 s, 720p, `generateAudio: false` |
| decisions | Gemini Decision 1 via `ifseen` | `ifseen test RULES --image X --json --provider gemini`; clips with `ifseen watch RULES --json`, `every: 500ms`, `realtime: false`, `skip_unchanged: false` |

Shared still prompt suffix (base images): *"Photoreal, natural and slightly imperfect: mild sensor
noise, a little compression, uneven real-world lighting, unstaged clutter, not a glossy advert,
no people looking at the camera."* Edits end with: *"Keep the exact same camera angle, framing,
lighting, grain, lens distortion and timestamp style; change only what is described. Photoreal."*
Clip prompts end with: *"Fixed static security camera, no camera movement, no cuts, realistic
natural motion, slightly grainy CCTV footage, keep the timestamp overlay."*

## Annotated stills (`stills/*.webp`)

Threshold in brackets. **Bold** = would fire.

| file | prompt (short) | rules → probability |
|---|---|---|
| `dog-couch.webp` | pet camera high in a living-room corner, golden retriever curled on a grey sofa | **dog-on-sofa (80%) 93.6%** · dog-on-floor (80%) 8.9% |
| `dog-floor.webp` | edit: sofa empty, dog lying on the rug in front of it | dog-on-sofa 6.2% · **dog-on-floor 94.6%** |
| `door-parcel.webp` | edit: brown cardboard parcel on the doormat | **parcel-left (85%) 94.6%** · doorstep-empty (80%) 7.7% |
| `door-empty.webp` | video-doorbell fisheye of a UK terrace doorstep, empty mat, overcast | parcel-left 6.0% · **doorstep-empty 89.0%** |
| `pot-boilover.webp` | edit: starchy foam boiling over the rim onto the hob | **boiling-over (80%) 94.5%** · gentle-simmer (80%) 6.3% |
| `pot-simmer.webp` | webcam above a hob, saucepan barely simmering, wooden spoon | boiling-over 12.7% · **gentle-simmer 82.8%** |
| `print-fail.webp` | USB webcam on a 3D printer, bird's nest of orange PLA spaghetti | **spaghetti (85%) 93.2%** · print-ok (80%) 7.9% |
| `print-good.webp` | edit: clean half-finished orange vase on the bed | spaghetti 8.9% · **print-ok 84.0%** |
| `laptop-unlocked.webp` | ceiling camera, empty desk, unlocked laptop showing spreadsheet + inbox | **laptop-unlocked-unattended (80%) 94.4%** · screen-locked (80%) 6.2% · person-at-desk (80%) 11.0% |
| `laptop-locked.webp` | edit: Windows lock screen | laptop-unlocked-unattended 9.1% · **screen-locked 92.1%** · person-at-desk 12.4% |
| `laptop-person.webp` | edit: worker in a grey jumper typing at the desk (also the clip's start frame) | laptop-unlocked-unattended 15.2% · screen-locked 9.0% · **person-at-desk 92.9%** |
| `room-occupied.webp` | edit: four people meeting, slide deck on the TV | **room-occupied (80%) 92.4%** · room-empty (80%) 9.2% |
| `room-empty.webp` | ceiling occupancy camera, empty glass-walled meeting room | room-occupied 9.8% · **room-empty 92.6%** |
| `printer-jam.webp` | phone photo of an MFP touchscreen: "Paper jam in Tray 2" | **paper-jam (80%) 94.1%** · printer-ready (80%) 6.1% |
| `printer-ready.webp` | edit: green tick, "Ready", Copy/Scan/Print tiles | paper-jam 7.3% · **printer-ready 95.3%** |
| `reception-visitor.webp` | edit: visitor with laptop bag waiting at the unattended counter | **visitor-waiting (80%) 88.9%** · reception-empty (80%) 4.4% |
| `reception-empty.webp` | high camera behind an empty corporate reception | visitor-waiting 5.4% · **reception-empty 95.0%** |

Rule text is in [`rules/`](rules/) (`pet.yaml`, `doorbell.yaml`, ...). All 8 pairs separated
cleanly; none were dropped. Expect small run-to-run variation: an earlier identical call on
`dog-couch` returned 92.6% for dog-on-sofa.

## Clips (`clips/*.mp4|webm`, `hero.*`)

Each clip is the Veo video (left) with a live panel (right) drawn from the real `ifseen watch`
timeline. Decision *i* is video time *i* × 0.5 s. Bars ease between decisions only for smooth
animation; printed numbers are always the latest real decision, and the FIRED flash appears at
the real fire time. The last frame is held for 1.25 s.

| clip | start frame / prompt | rules | real timeline |
|---|---|---|---|
| `dog` | `dog-floor` still; "the retriever gets up, walks over and jumps onto the sofa, lies down" | dog-on-sofa (80%), dog-on-floor (80%) | floor 93% → fires at 0.0 s; sofa 6% … 28% (3.5 s), 61% (4.0 s), **fires 92.8% at 4.5 s**, 95.1% at 5.0 s |
| `parcel` | `door-empty` still; "courier in hi-vis places a parcel on the mat and walks away" | parcel-left (85%), person-at-door (80%) | person-at-door **fires 83.6% at 1.5 s**; parcel-left 14% → 77% (4.0 s, courier still there) → **fires 94.5% at 4.5 s** as he leaves |
| `desk` | `laptop-person` still; "the worker stands up and walks away, laptop left unlocked" | laptop-unlocked-unattended (80%), person-at-desk (80%) | person-at-desk 90% (fires at 0.0 s) → 47.5% (2.0 s); unlocked-unattended 10% → **fires 82.0% at 3.0 s**, 90.5% by 5.5 s |

`hero.mp4` / `hero.webm` are the three clips back to back (21.75 s). `hero.gif` is the dog clip
only (900 px, 12 fps, 3.4 MB) for the project README: `docs/media/hero.gif`. Posters:
`hero-poster.webp`, `clips/*-poster.webp`.

Full per-decision numbers: `data/watch_dog.jsonl`, `data/watch_parcel.jsonl`,
`data/watch_desk.jsonl` (raw `--json` events); stills: `data/stills.jsonl`.

## Known artefacts

These are generation artefacts, not ifseen behaviour: the Veo pet-cam clip briefly draws a
second, garbled timestamp; burned-in timestamps on the stills are invented and inconsistent;
the boil-over foam is a little stylised.
