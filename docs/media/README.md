# Demo media

> **AI-generated scenes, real ifseen outputs.** Every photo and video here was generated with
> Google models on Vertex AI (the two HMI screens are drawn with PIL). None of it is real
> footage. Every probability, token count, latency and FIRED moment shown on top of it is a
> real, unedited output from `ifseen`, recorded on 2026-11-19: Gemini Decision 1
> (`--provider gemini`) for everything, and TypeSafe Jev (`--provider jev`) as well for the
> use-case set. Raw outputs are in [`data/`](data/), rule files in [`rules/`](rules/).

## Use cases: things with no API (`stills/{hob,washer,bay,shelf,hmi}-*.webp`, `clips/{hob,hivis}.*`)

Generated with the same models and settings as below (`gemini-2.5-flash-image` on Vertex AI
`global`, Application Default Credentials; Veo `veo-3.1-lite-generate-001`, `us-central1`).
Each still was run once per provider with
`ifseen test RULES --image X --json --provider gemini|jev`. The annotated stills show both:
the big number and main bar are Gemini, the thin bar below is Jev. Raw output:
[`data/usecases.jsonl`](data/usecases.jsonl). Rules: `rules/{hob,appliance,hivis,shelf,hmi}.yaml`
(threshold 80%; the main rule of each set uses `false_means`).

| file | prompt (short) | rules → Gemini / Jev |
|---|---|---|
| `hob-unattended.webp` | edit of `hob-cooking`: person removed, burner still lit, steam rising | **hob-unattended 94.4% / 96%** · person-cooking 6.6% / 32% · hob-off 3.6% / 1% |
| `hob-cooking.webp` | high corner camera in a UK kitchen, person stirring a frying pan on a lit gas hob | hob-unattended 3.2% / 2% · **person-cooking 94.3% / 95%** · hob-off 5.6% / 2% |
| `hob-off.webp` | edit of `hob-unattended`: burners off, no steam (second attempt, see below) | hob-unattended 21.4% / 26% · person-cooking 10.8% / 12% · hob-off 52.5% / 8% |
| `washer-done.webp` | edit: display reads "End", drum still | **cycle-finished 95.7% / 98%** · cycle-running 4.8% / 2% |
| `washer-running.webp` | webcam on a front-loader in a utility room, display "0:42", clothes in soapy water | cycle-finished 5.8% / 2% · **cycle-running 93.5% / 96%** |
| `bay-nohivis.webp` | edit of `bay-hivis`: vest replaced by a grey hoodie | **no-hivis 91.9% / 98%** · hivis-worn 5.1% / 2% |
| `bay-hivis.webp` | ceiling CCTV over a warehouse loading bay, worker in a yellow hi-vis vest scanning a pallet | no-hivis 4.7% / 4% · **hivis-worn 92.3% / 97%** |
| `bay-empty.webp` | edit of `bay-hivis`: worker removed (also the hi-vis clip's start frame) | no-hivis 9.2% / 7% · hivis-worn 9.7% / 3% |
| `shelf-gap.webp` | edit of `shelf-full`: products removed from the middle of a shelf (the model cleared more than asked) | **shelf-gap 94.3% / 97%** · shelf-full 5.9% / 1% |
| `shelf-full.webp` | shelf camera facing one bay: tomatoes, beans, pasta sauce, pasta, fully stocked (second attempt) | shelf-gap 26.6% / 33% · shelf-full 56.1% / 25% |
| `hmi-alarm.webp` | PIL: legacy "FILLMASTER HMI" in a remote-desktop window, red ALARM 2041 banner, pump tripped | **alarm-active 97.0% / 99%** · normal-operation 2.5% / 1% |
| `hmi-normal.webp` | PIL: same screen, "No active alarms", pump running | alarm-active 1.4% / 3% · **normal-operation 95.5% / 98%** |

Every headline rule separated cleanly on both providers. Two opposite rules were weak and are
shown as such: `hob-off` (52.5% / 8% on the hob-off frame, food is still in the pan) and
`shelf-full` (56.1% / 25% on the stocked shelf). Neither fired.

**Regenerated, not hidden.** The first `hob-off` edit still had a lit blue flame and steam
(both providers correctly scored hob-unattended 89.1% / 95% on it), and the first
`shelf-full` base had visible gaps (shelf-full 22.5% / 15%). Both were mislabelled
generations, so they were regenerated (with a new shelf-gap edit) and re-tested; the first
attempts aren't published.

Clips (`ifseen watch rules/clip_*.yaml --json`, `every: 500ms`, `realtime: false`,
`skip_unchanged: false`, both providers; raw: `data/watch_hob*.jsonl`, `data/watch_hivis*.jsonl`).
The panel's big numbers and FIRED banner are Gemini; "jev N%" and the event log show Jev's real
run:

| clip | start frame / prompt | real timeline |
|---|---|---|
| `hob` | `hob-cooking`; "the person rests the spatula, walks out through the doorway; burner stays lit, steam keeps rising" | Gemini: person-in-kitchen fires 93.8% at 0.0 s; hob-unattended 10% (1.0 s), 56% (2.5 s), 73% (3.0 s, cook in the doorway), **fires 89.4% at 4.0 s**. Jev: hob-unattended 2-17% until 3.5 s, 51% at 4.0 s, **fires 95% at 4.5 s** |
| `hivis` | `bay-empty`; "a worker in a dark grey hoodie, no hi-vis, walks in from the dock door to the pallet" | Gemini: bay-empty fires 89.1% at 0.0 s (worker a speck in the doorway); **no-hivis fires 91.6% at 0.5 s**, 91-94% to the end. Jev: bay-empty 84% at 0.0 s, **no-hivis fires 96% at 0.5 s**, 96-98% after |

`hero.mp4` / `hero.webm` are now the hob, hi-vis and dog clips back to back (21.75 s), and
`hero.gif` is the hob clip (900 px, 12 fps, 1.9 MB) for the project README. Posters:
`hero-poster.webp`, `clips/*-poster.webp`.

Generation count for this set: 13 image generations (4 bases, 9 edits including 3 regenerations)
and 2 Veo clips. Artefacts: a ceiling dome camera appears inside some kitchen and loading-bay
frames; the shelf edit removed far more stock than asked and shifted the framing slightly;
the hob-off edit re-framed the kitchen a little.

<details><summary>Full prompts for the use-case set</summary>

```text
SUFFIX: Photoreal, natural and slightly imperfect: mild sensor noise, a little compression, uneven real-world lighting, unstaged clutter, not a glossy advert, no people looking at the camera.
washer_running: A cheap webcam photo taken from about one metre away of the control panel of an ordinary white front-loading washing machine in a small UK utility room. The machine's small digital display clearly shows the remaining time '0:42' in bright segmented digits, with the 'Wash' indicator lit and the programme dial set to Cotton 40. The round drum door is visible in the lower part of the frame with clothes tumbling in soapy water. Slight glare on the display, laundry basket and detergent bottle nearby. Photoreal, natural and slightly imperfect: mild sensor noise, a little compression, uneven real-world lighting, unstaged clutter, not a glossy advert, no people looking at the camera.
hob_cooking: A wide-angle home security camera mounted high in the corner of an ordinary UK domestic kitchen, looking down at a gas hob on the worktop. A frying pan sits on a lit front burner with a visible blue flame, and steam is rising from the pan. A person in a T-shirt stands at the hob stirring the pan with a wooden spatula, seen from behind and slightly to the side. An open doorway to the hall is visible on the right side of the frame. Small white CCTV timestamp overlay in the top-left corner. Photoreal, natural and slightly imperfect: mild sensor noise, a little compression, uneven real-world lighting, unstaged clutter, not a glossy advert, no people looking at the camera.
bay_hivis: A ceiling-mounted CCTV camera in a warehouse loading bay, looking down at an open roller-shutter dock door, a pallet of shrink-wrapped boxes and a yellow-painted pedestrian walkway on a scuffed concrete floor. One warehouse worker stands next to the pallet scanning a box label with a handheld scanner; he wears a fluorescent yellow high-visibility vest with silver reflective stripes over a dark top, jeans and safety boots. Harsh mixed fluorescent and daylight lighting from the dock door. CCTV timestamp overlay in the top-left corner and the camera name 'DOCK 3' in the bottom-right. Photoreal, natural and slightly imperfect: mild sensor noise, a little compression, uneven real-world lighting, unstaged clutter, not a glossy advert, no people looking at the camera.
shelf_full: A fixed shelf-monitoring camera in a UK supermarket aisle, looking straight at one section of shelving stocked with tins of soup on the upper shelves and jars of pasta sauce on the lower shelves, with small price labels on the shelf edges. Every facing is fully stocked, products pulled forward to the front edge, no gaps anywhere. Slight wide-angle distortion, flat fluorescent lighting. Photoreal, natural and slightly imperfect: mild sensor noise, a little compression, uneven real-world lighting, unstaged clutter, not a glossy advert, no people looking at the camera.
EDIT SUFFIX: Keep the exact same camera angle, framing, lighting, grain, lens distortion and timestamp style; change only what is described. Photoreal.
washer_done<-washer_running: Change only the washing machine's digital display: it now shows the word 'End' in the same segmented digits instead of the time, and the 'Wash' indicator is off. The cycle has finished: the drum is still, the clothes rest damp at the bottom of the drum and there is no soapy water. Keep the exact same camera angle, framing, lighting, grain, lens distortion and timestamp style; change only what is described. Photoreal.
hob_unattended<-hob_cooking: Remove the person completely; the kitchen is now empty with nobody in it. The front gas burner is still lit under the frying pan and steam is still rising from the pan, spatula resting in the pan. Keep the exact same camera angle, framing, lighting, grain, lens distortion and timestamp style; change only what is described. Photoreal.
bay_nohivis<-bay_hivis: Change only the worker's clothing: he is no longer wearing a high-visibility vest; he now wears a plain dark grey hoodie and jeans, with no fluorescent or reflective clothing anywhere on him. Same pose, same scanner. Keep the exact same camera angle, framing, lighting, grain, lens distortion and timestamp style; change only what is described. Photoreal.
bay_empty<-bay_hivis: Remove the worker completely; the loading bay is empty with nobody in it. The pallet and everything else stays exactly where it is. Keep the exact same camera angle, framing, lighting, grain, lens distortion and timestamp style; change only what is described. Photoreal.
shelf_gap<-shelf_full: Remove all the jars from the middle part of the second-lowest shelf, leaving a clear empty gap about a quarter of the shelf wide where the bare white shelf and back panel are visible; the price label for the missing product stays on the shelf edge. Everything else stays fully stocked. Keep the exact same camera angle, framing, lighting, grain, lens distortion and timestamp style; change only what is described. Photoreal.
hob_off<-hob_unattended: Turn the hob off: no flame under any burner and no steam at all; the frying pan sits cold on the hob with the spatula in it. The kitchen stays empty. Keep the exact same camera angle, framing, lighting, grain, lens distortion and timestamp style; change only what is described. Photoreal.
hob_off(v2)<-hob_unattended: Switch the gas hob off completely: there is no blue flame under any burner, all burner rings are dark and unlit, and there is no steam at all; the frying pan sits cold and still on the hob with the spatula in it. The kitchen stays empty. Keep the exact same camera angle, framing, lighting, grain, lens distortion and timestamp style; change only what is described. Photoreal.
shelf_full(v2): A fixed shelf-monitoring camera in a UK supermarket, mounted opposite one bay of shelving about two metres away, looking straight at four shelves: tins of chopped tomatoes on the top shelf, tins of baked beans on the second, jars of pasta sauce on the third and bags of pasta on the bottom shelf, each with small yellow price labels on the shelf edge. Every shelf is completely and neatly fully stocked right across from edge to edge, products pulled forward, no gaps or missing items anywhere. Flat fluorescent lighting, slight wide-angle distortion. Photoreal, natural and slightly imperfect: mild sensor noise, a little compression, uneven real-world lighting, unstaged clutter, not a glossy advert, no people looking at the camera.
shelf_gap(v2)<-shelf_full(v2): Remove the jars of pasta sauce from the middle third of the third shelf only, leaving one clear empty gap where the bare shelf and the back panel are visible; the yellow price label for the missing product stays on the shelf edge. Every other shelf and every other product stays exactly the same and fully stocked. Keep the exact same camera angle, framing, lighting, grain, lens distortion and timestamp style; change only what is described. Photoreal.
VEO hob <- hob_cooking: The person stops stirring, rests the spatula in the pan, turns and walks out of the kitchen through the open doorway on the right and disappears down the hall. The gas burner stays lit under the frying pan and steam keeps rising from the pan. For the rest of the clip the kitchen is empty. Fixed static security camera, no camera movement, no cuts, realistic natural motion, slightly grainy CCTV footage, keep the timestamp overlay.
VEO hivis <- bay_empty: A warehouse worker wearing a plain dark grey hoodie and jeans, with no high-visibility vest and no reflective clothing, walks in from the open dock door, crosses the loading bay floor and stops beside the pallet to look at a box label. Fixed static security camera, no camera movement, no cuts, realistic natural motion, slightly grainy CCTV footage, keep the timestamp overlay.
```

</details>

## Home and office set

### Models

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

### Annotated stills (`stills/*.webp`)

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

### Clips (`clips/{dog,parcel,desk}.*`)

Each clip is the Veo video (left) with a live panel (right) drawn from the real `ifseen watch`
timeline. Decision *i* is video time *i* × 0.5 s. Bars ease between decisions only for smooth
animation; printed numbers are always the latest real decision, and the FIRED flash appears at
the real fire time. The last frame is held for 1.25 s.

| clip | start frame / prompt | rules | real timeline |
|---|---|---|---|
| `dog` | `dog-floor` still; "the retriever gets up, walks over and jumps onto the sofa, lies down" | dog-on-sofa (80%), dog-on-floor (80%) | floor 93% → fires at 0.0 s; sofa 6% … 28% (3.5 s), 61% (4.0 s), **fires 92.8% at 4.5 s**, 95.1% at 5.0 s |
| `parcel` | `door-empty` still; "courier in hi-vis places a parcel on the mat and walks away" | parcel-left (85%), person-at-door (80%) | person-at-door **fires 83.6% at 1.5 s**; parcel-left 14% → 77% (4.0 s, courier still there) → **fires 94.5% at 4.5 s** as he leaves |
| `desk` | `laptop-person` still; "the worker stands up and walks away, laptop left unlocked" | laptop-unlocked-unattended (80%), person-at-desk (80%) | person-at-desk 90% (fires at 0.0 s) → 47.5% (2.0 s); unlocked-unattended 10% → **fires 82.0% at 3.0 s**, 90.5% by 5.5 s |

These three clips used to make up `hero.*` and `hero.gif` (the dog clip); see the use-case
section above for the current hero.

Full per-decision numbers: `data/watch_dog.jsonl`, `data/watch_parcel.jsonl`,
`data/watch_desk.jsonl` (raw `--json` events); stills: `data/stills.jsonl`.

## Known artefacts

These are generation artefacts, not ifseen behaviour: the Veo pet-cam clip briefly draws a
second, garbled timestamp; burned-in timestamps on the stills are invented and inconsistent;
the boil-over foam is a little stylised.
