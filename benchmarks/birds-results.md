# Bird benchmark: decision model vs LLM vs free local model

Run 2026-11-19 with `benchmarks/birds.py`: 8 images (5 birds, 3 non-birds) × 3 repeats per engine.

**The task:** is there a bird? → if so, which one, from a short list of 10 UK garden birds
plus `other` → if `other`, pick from a wider list of 41 species. Robin and magpie are on the
short list. Eagle, owl and puffin are not, so they exercise the wider-list step. Non-birds:
zebra, sunflower, and a nest of blue eggs (the hard negative). LLMs got one call:
"What bird is this?" (free text).

| engine | species correct | median time / image | cost / 1,000 images | notes |
|---|---|---|---|---|
| Gemini Decision 1, 3 separate calls | **8/8** | 1.01 s | $0.26 | |
| Gemini Decision 1, steps 1+2 in one call | **8/8** | **0.69 s** | **$0.19** | the shared image is billed once |
| Azure gpt-5.4-mini (free text) | **8/8** | 1.14 s | $0.44 | |
| Azure gpt-5.4-nano (free text) | 79% | 1.81 s | $0.12 | nest → "Bluebird"; answers varied between runs |
| Azure gpt-4.1-mini (free text) | 7/8 | 1.92 s | $0.30 | nest → "American Robin" |
| CLIP ViT-B/32, local (MPS) | 7/8 | **0.06 s** | **$0** | nest → "Eurasian jay" |
| SigLIP base, local (MPS) | **8/8** | **0.09 s** | **$0** | scores aren't calibrated probabilities |

## What we learned

- **The nest was the only image that split the field.** The decision model, gpt-5.4-mini and
  SigLIP said "no bird". The others named a bird from the colour of the eggs.
- **Decision model probabilities are usable as thresholds.** "Bird visible" scored
  0.86-0.91 on birds and 0.11-0.16 on non-birds. SigLIP picked the right labels but its raw
  scores (often below 0.05, because each label is scored independently) can't be thresholded
  the same way. CLIP's softmax scores sit in between.
- **Ask in one call wherever you can.** Putting the yes/no and the short-list choice in one
  request cost 25% less and was about 30% faster, because the image is billed and uploaded
  once. ifseen's one-request-per-frame design relies on the same effect.
- **The wider list adds cost.** Its 41 option descriptions added about 1,600 input tokens to
  that call.
- **Free local models are 10-20× faster and cost nothing**, once you've downloaded about 600 MB
  and spent 1-2 s loading the model. But they only rank the labels you give them; they can't
  answer open-ended or audio questions.
- **API times are network-bound** (UK → Google/Azure) and varied a lot (0.3-3.4 s per call).

## Caveats

There are only 8 images, so treat these as directional numbers. Prices are list prices
(Decision $0.10/M input; gpt-5.4-mini $0.75/$4.50; gpt-5.4-nano $0.20/$1.25; gpt-4.1-mini
$0.40/$1.60 per M input/output). Local timings are from an Apple Silicon Mac using MPS, after a
warm-up run.

## Reproduce

Put `robin.jpg magpie.jpg puffin.jpg eagle.jpg owl.jpg zebra.jpg nest.jpg sunflower.jpg` in
a folder (not committed for licensing reasons), then:

```bash
GEMINI_DECISIONS_KEY=... python benchmarks/birds.py ./images --engines decision,decision+
AZ_BASE=https://<res>.openai.azure.com/openai/v1 AZ_KEY=... AZ_DEPLOYMENTS=gpt-5.4-mini \
  python benchmarks/birds.py ./images --engines llm
pip install torch transformers sentencepiece protobuf
python benchmarks/birds.py ./images --engines local
```
