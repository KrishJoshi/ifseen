# Hard-rules benchmark: where free local models stop being good enough

Run 2026-11-19 with `benchmarks/hard_rules.py`: 78 images + 12 audio clips, every API call
made once.

**The claim we tested:** the [bird benchmark](birds-results.md) showed free local zero-shot
models (SigLIP, CLIP) match decision models at *naming objects*. They should be weaker at
rules about **screen text, spatial relations, scene states and audio**. The results back that
up for screen text, states and audio. They don't for the simple spatial rules we tried.

## Data

| category | captures | rules (each capture is asked all of its category's rules) |
|---|---|---|
| screen | 20 generated screenshots: GitHub Actions (light and dark), GitLab, Jenkins and terminal CI pages that are failed, passed or running; mac, Windows and browser error dialogs; a plain editor and mail app; a "Save changes?" and an "Update available" dialog as look-alikes | "The CI build shown on screen has failed." · "An error message dialog is showing on screen." |
| spatial | 26 Wikimedia Commons photos: dog on a sofa (5), dog on the floor (5), empty sofa (5, one with children on it); cat on a table/counter (5), cat on the floor (4), empty kitchen (2) | "A dog is on the sofa." · "A cat is on a table or kitchen counter." |
| scene | 32 Commons photos: open (5) vs closed (6) doors; boiling (6) vs not boiling (5) pots, including apples floating in still water; failed "spaghetti" (5) vs good (5) 3D prints | "The door is open." · "Water is boiling in a pot." · "The 3D print has failed and turned into a tangle of loose filament." |
| audio | 12 `say` clips in 3 voices: the name Krish, with and without a question; questions without the name; plain statements; "Chris" as a sound-alike | "Someone says the name Krish." · "Someone is asking a question." |

I looked at every photo and labelled it by what's visible. I dropped two after a first run as
ambiguous: a "good" Benchy with visible ooze defects, and a heavily strung but intact print.
Every engine was scored without them. Each rule is scored only on its own group (the dog rule
on the dog/sofa photos, for example), because a door photo is a trivially easy "no" for the
dog rule. Each rule also has a contrast phrase describing what "no" looks like (for example
"The door is closed."). That phrase is used by the local `contrast` variants and by
`decision+fm`, which sends it as `false_description`.

## Results

**acc** is accuracy at a 0.5 threshold. **AUC** is the mean per-rule ROC AUC: 1.00 means some
threshold separates every yes from every no. **pos ≥ / neg ≤** are the lowest score on a true
capture and the highest on a false one, pooled across the category's rules. Latency is the
median per capture. Cost is per 1,000 captures.

### screen text

| engine | acc | AUC | pos ≥ / neg ≤ | latency | cost / 1k |
|---|---|---|---|---|---|
| Gemini Decision 1 | **100%** | **1.00** | 0.90 / 0.12 | 596 ms | $0.13 |
| Gemini Decision 1 + contrast | **100%** | **1.00** | 0.91 / 0.11 | 374 ms | $0.13 |
| TypeSafe Jev 1.14 | **100%** | **1.00** | 0.99 / 0.49 | **174 ms** | $0.13 |
| TypeSafe Jev 1.14 + contrast | **100%** | **1.00** | 0.99 / 0.19 | **172 ms** | $0.13 |
| Azure gpt-5.4-mini | 98% | **1.00** | 0.99 / 0.98 | 1,152 ms | $1.01 |
| SigLIP, ifseen `local` | 75% | 0.82 | 0.03 / 0.93 | 20 ms | $0 |
| CLIP, generic captions | 52% | 0.86 | 0.65 / 0.99 | 12 ms | $0 |

SigLIP spots an error dialog (AUC 1.00) but can't read whether a CI run failed (AUC 0.64, 55%
accurate). A red "Failure" and a green "Success" look the same to it. Contrast phrases made
the screen rules worse for both local models (AUC 0.39-0.58).

### spatial relations

| engine | acc | AUC | pos ≥ / neg ≤ | latency | cost / 1k |
|---|---|---|---|---|---|
| Gemini Decision 1 | **100%** | **1.00** | 0.88 / 0.15 | 679 ms | $0.13 |
| Gemini Decision 1 + contrast | **100%** | **1.00** | 0.91 / 0.11 | 472 ms | $0.13 |
| TypeSafe Jev 1.14 | **100%** | **1.00** | 0.83 / 0.10 | **192 ms** | $0.10 |
| TypeSafe Jev 1.14 + contrast | **100%** | **1.00** | 0.80 / 0.08 | **185 ms** | $0.10 |
| Azure gpt-5.4-mini | 96% | **1.00** | 0.98 / 0.95 | 2,298 ms | $0.80 |
| SigLIP, ifseen `local` | **100%** | **1.00** | 0.54 / 0.26 | 18 ms | $0 |
| CLIP, contrast | 77% | 0.87 | 0.11 / 0.96 | 11 ms | $0 |

This contradicts the claim. SigLIP's own match score separated "dog on the sofa" from "dog on
the floor" and "empty sofa" perfectly, and the same for the cat. Two caveats: these are easy
spatial cases (sofa photos are cushion close-ups, floor photos show floor), and the +3 logit
offset that puts them on the right side of 0.5 was chosen on this same data. CLIP was weaker.

### scene states

| engine | acc | AUC | pos ≥ / neg ≤ | latency | cost / 1k |
|---|---|---|---|---|---|
| Gemini Decision 1 | **100%** | **1.00** | 0.55 / 0.33 | 763 ms | $0.13 |
| Gemini Decision 1 + contrast | **100%** | **1.00** | 0.86 / 0.16 | 439 ms | $0.14 |
| TypeSafe Jev 1.14 | **100%** | **1.00** | 0.65 / 0.16 | **188 ms** | $0.11 |
| TypeSafe Jev 1.14 + contrast | **100%** | **1.00** | 0.70 / 0.16 | **196 ms** | $0.11 |
| Azure gpt-5.4-mini | 91% | 0.99 | 0.88 / 0.97 | 1,580 ms | $0.83 |
| SigLIP, ifseen `local` (contrast) | 78% | 0.94 | 0.14 / 0.55 | 19 ms | $0 |
| CLIP, contrast | 84% | 0.91 | 0.07 / 0.71 | 12 ms | $0 |

With a contrast phrase, SigLIP got open vs closed doors and failed vs good prints right
(AUC 1.00). It scored boiling pots too low: 5 of 6 boiling pots fell under 0.5. Without a
contrast, the statement alone barely ranks states (AUC 0.67), because a closed door still
matches "door". Wrapping both phrases as "a photo where ..." reached 97% on scenes but hurt
the other categories, so I'd treat that as overfitting.

### audio

| engine | acc | AUC | pos ≥ / neg ≤ | latency | cost / 1k |
|---|---|---|---|---|---|
| Gemini Decision 1 | **100%** | **1.00** | 0.52 / 0.47 | 539 ms | $0.025 |
| Gemini Decision 1 + contrast | **100%** | **1.00** | 0.92 / 0.49 | 337 ms | $0.028 |
| Jev, gpt-5.4-mini, SigLIP, CLIP | n/a | | | | |

Jev and the local models are image-only, and we didn't send audio to the Azure deployment. The
closest calls were the "Chris" sound-alikes, at 0.46-0.49 for "says the name Krish": correct,
but only just. At ifseen's default 0.8 threshold they're safely below.

## Local scoring variants tried

All variants use one image embedding and cached caption embeddings. The table shows mean
per-rule AUC, then accuracy at 0.5.

| variant | SigLIP screen | SigLIP spatial | SigLIP scene | CLIP screen | CLIP spatial | CLIP scene |
|---|---|---|---|---|---|---|
| `raw`: sigmoid(logit) | 0.82 / 80% | 1.00 / 65% | 0.67 / 53% | n/a | n/a | n/a |
| `raw_offset`: sigmoid(logit + 3) | 0.82 / 75% | 1.00 / 100% | 0.67 / 66% | n/a | n/a | n/a |
| `generic`: softmax vs 4 generic captions | 0.83 / 65% | 1.00 / 46% | 0.59 / 50% | 0.86 / 52% | 0.98 / 58% | 0.50 / 56% |
| `contrast`: softmax(statement, contrast) | 0.52 / 38% | 0.78 / 62% | 0.94 / 78% | 0.39 / 45% | 0.87 / 77% | 0.91 / 84% |
| `contrast_photo`: "a photo where ..." | 0.58 / 40% | 0.70 / 65% | 0.94 / 97% | 0.49 / 48% | 0.87 / 73% | 0.94 / 88% |

ifseen's `local` provider uses `raw_offset` for rules without `false_means` and `contrast`
for rules with one. The table rows marked "ifseen `local`" give the scene rules a contrast and
leave the others without one. Raw SigLIP scores separate well (spatial AUC 1.00) but sit far
below 0.5 for true captions, hence the offset. Presence captions are even lower: "a photo of
a dog." scored at least 0.13 with a dog in frame and at most 0.02 without. So ifseen's prefilter
default threshold is 0.05, not 0.5.

## Conclusion

- **Jev (added 2026-11-19, same 78 images, through ifseen's `jev` provider) matched Gemini
  Decision 1 at 100% on every image category, at about 3-4× lower latency (~180 ms median vs
  ~600 ms) and similar cost.** Its "yes" scores were higher (screen text ≥ 0.99), and on screen
  text its highest "no" (0.49) was closer to 0.5 than Gemini's, which `false_means` fixed
  (0.19). Jev can't hear, so audio rules still need Gemini.

- **Decision models win wherever the answer depends on reading or understanding the scene.**
  That covers CI status text (100% vs 55% for SigLIP), boiling vs still water, and anything
  audio. They also give the most usable probabilities: a 0.5 threshold was right every time,
  and contrast phrases (`false_means`) widened the gap further.
- **Free local models are competitive at "is X there" and simple "X on Y" rules,** at about
  20 ms and $0. Their scores aren't calibrated, though, and the right threshold differs per
  rule, so you need `ifseen test`.
- **gpt-5.4-mini ranks well (AUC ~1.0) but answers in extremes.** Its false "yes" answers came
  at 0.87-0.98, for example "Save changes?" read as an error dialog and a closed wooden door
  read as open. It's about 6-8× the cost and 2-3× the latency of the decision model.
- **The cascade is the practical combination:** a local "a photo of a dog." prefilter is free,
  and the decision model only runs when it passes.

## Caveats

These are small sets (2-6 positives per rule), so treat the numbers as directional. The
screenshots are synthetic. The decision-model latencies are network-bound from the UK and
varied between runs; the `+contrast` run went second, on warm connections. Local timings are
on Apple Silicon with MPS after warm-up. Total API spend was about $0.09 ($0.02 decision,
$0.07 gpt-5.4-mini). Prices: Decision $0.10/M input tokens (about 1,300 tokens per 800 px
photo or 1280×800 screenshot, about 250 per 4 s clip); gpt-5.4-mini $0.75/M input and
$4.50/M output (about 950 input and 21 output tokens per image).

## Reproduce

Photos aren't committed (licensing). The search terms used were "dog on sofa", "dog lying on
floor", "sofa living room", "cat on table", "cat on kitchen counter", "cat on floor", "open
door", "closed wooden door", "boiling water pot", "saucepan water", "pot on gas stove",
"cooking pot filled with water", "stock pot stove", "3D print failed" and "Prusa i3 printing".
Name them as `PHOTO_TRUTH` in `hard_rules.py` expects.

```bash
python benchmarks/hard_rules_screens.py /tmp/hard-rules/img
say -v Daniel -o name_q_hey_krish.wav --data-format=LEI16@16000 "Hey Krish, can you take a look at the failing test?"   # etc, see AUDIO_TRUTH
GEMINI_DECISIONS_KEY=... python benchmarks/hard_rules.py /tmp/hard-rules/img /tmp/hard-rules/audio --engines decision,decision+fm
AZ_BASE=https://<res>.openai.azure.com/openai/v1 AZ_KEY=... python benchmarks/hard_rules.py ... --engines llm
pip install 'ifseen[local]' && python benchmarks/hard_rules.py ... --engines local
```
