"""Bird benchmark: decision model vs LLM vs free local model.

Task per image:
  1. is there a bird?            (no bird -> stop)
  2. which bird? short list + "other"
  3. if "other": which bird? wider list

Engines
  decision    Gemini Decision 1, three separate calls (as above)
  decision+   Gemini Decision 1, steps 1+2 asked in ONE call (shared input billed once)
  llm:<dep>   Azure OpenAI chat model, single call: "What bird is this?" (free text)
  local:<m>   Hugging Face zero-shot image classifier (CLIP / SigLIP) on this machine, same 3 steps

Env:
  GEMINI_DECISIONS_KEY       key for the Decisions API only
  AZ_BASE, AZ_KEY            Azure OpenAI v1 base (https://<res>.openai.azure.com/openai/v1) + key
  AZ_DEPLOYMENTS             comma-separated deployments to test (default gpt-5.4-mini)

    python benchmarks/birds.py IMAGE_DIR [--repeats 3] [--engines decision,decision+,llm,local]
"""

from __future__ import annotations

import argparse
import base64
import json
import os
import statistics
import sys
import time
from dataclasses import dataclass, field
from pathlib import Path

import httpx

# -- task definition ---------------------------------------------------------------------------

SHORT = {  # UK garden birds
    "european_robin": "European robin",
    "eurasian_magpie": "Eurasian magpie",
    "common_blackbird": "Common blackbird",
    "blue_tit": "Blue tit",
    "great_tit": "Great tit",
    "house_sparrow": "House sparrow",
    "wood_pigeon": "Wood pigeon",
    "carrion_crow": "Carrion crow",
    "common_starling": "Common starling",
    "goldfinch": "European goldfinch",
}
WIDE = {
    "bald_eagle": "Bald eagle",
    "golden_eagle": "Golden eagle",
    "white_tailed_eagle": "White-tailed eagle",
    "osprey": "Osprey",
    "red_kite": "Red kite",
    "common_buzzard": "Common buzzard",
    "peregrine_falcon": "Peregrine falcon",
    "kestrel": "Common kestrel",
    "barn_owl": "Barn owl",
    "tawny_owl": "Tawny owl",
    "snowy_owl": "Snowy owl",
    "spectacled_owl": "Spectacled owl",
    "great_horned_owl": "Great horned owl",
    "atlantic_puffin": "Atlantic puffin",
    "razorbill": "Razorbill",
    "guillemot": "Common guillemot",
    "herring_gull": "Herring gull",
    "northern_gannet": "Northern gannet",
    "cormorant": "Great cormorant",
    "mallard": "Mallard",
    "mute_swan": "Mute swan",
    "canada_goose": "Canada goose",
    "grey_heron": "Grey heron",
    "kingfisher": "Common kingfisher",
    "flamingo": "Flamingo",
    "peafowl": "Indian peafowl",
    "emperor_penguin": "Emperor penguin",
    "toucan": "Toco toucan",
    "macaw": "Scarlet macaw",
    "cockatoo": "Sulphur-crested cockatoo",
    "hummingbird": "Hummingbird",
    "ostrich": "Ostrich",
    "pheasant": "Common pheasant",
    "woodpecker": "Great spotted woodpecker",
    "eurasian_jay": "Eurasian jay",
    "wren": "Eurasian wren",
    "chaffinch": "Common chaffinch",
    "barn_swallow": "Barn swallow",
    "northern_cardinal": "Northern cardinal",
    "blue_jay": "Blue jay",
    "american_robin": "American robin",
}
OWLS = {"barn_owl", "tawny_owl", "snowy_owl", "spectacled_owl", "great_horned_owl"}

# image stem -> accepted species keys (None = no bird). LLM answers graded by keywords.
TRUTH: dict[str, set[str] | None] = {
    "robin": {"european_robin"},
    "magpie": {"eurasian_magpie"},
    "puffin": {"atlantic_puffin"},
    "eagle": {"bald_eagle"},
    "owl": OWLS,
    "zebra": None,
    "nest": None,
    "sunflower": None,
}
LLM_KEYWORDS = {
    "robin": (["robin"], ["american"]),
    "magpie": (["magpie"], []),
    "puffin": (["puffin"], []),
    "eagle": (["bald eagle"], []),
    "owl": (["owl"], []),
}
NO_BIRD_WORDS = ["no bird", "not a bird", "there is no bird", "none"]

DECISION_URL = "https://generativelanguage.googleapis.com/v1beta/decisions"
PRICE = {  # USD per 1M tokens (input, output)
    "gemini-decision-1": (0.10, 0.0),
    "gpt-5.4-mini": (0.75, 4.50),
    "gpt-5.4-nano": (0.20, 1.25),
    "gpt-4.1-mini": (0.40, 1.60),
    "local": (0.0, 0.0),
}
LLM_PROMPT = (
    "What bird is this? Reply with just the common species name. "
    "If there is no bird in the image, reply exactly: no bird"
)
BIRD_THRESHOLD = 0.5


@dataclass
class Result:
    verdict: str  # "none" | species key | free text (llm)
    correct_detection: bool
    correct_species: bool
    calls: int = 0
    input_tokens: int = 0
    output_tokens: int = 0
    cost: float = 0.0
    latency_ms: float = 0.0
    steps: list[str] = field(default_factory=list)


def grade(image: str, verdict_species: str | None) -> tuple[bool, bool]:
    truth = TRUTH[image]
    if truth is None:
        return verdict_species is None, verdict_species is None
    if verdict_species is None:
        return False, False
    return True, verdict_species in truth


def grade_llm(image: str, text: str) -> tuple[bool, bool]:
    t = text.lower().strip()
    said_none = any(w in t for w in NO_BIRD_WORDS)
    if TRUTH[image] is None:
        return said_none, said_none
    if said_none:
        return False, False
    must, must_not = LLM_KEYWORDS[image]
    ok = all(m in t for m in must) and not any(n in t for n in must_not)
    return True, ok


# -- engines ---------------------------------------------------------------------------------


class Decision:
    def __init__(self, key: str, combined: bool):
        self.key = key
        self.combined = combined
        self.name = "decision+ (1 call for steps 1+2)" if combined else "decision (3 steps)"
        self.client = httpx.Client(timeout=60)

    def _ask(self, jpeg_b64: str, questions: dict, r: Result) -> dict:
        body = {
            "model": "gemini-decision-1",
            "input": [
                {"type": "text", "text": "Photo:\n"},
                {"type": "image", "data": jpeg_b64, "mime_type": "image/jpeg"},
            ],
            "questions": questions,
        }
        t0 = time.perf_counter()
        resp = self.client.post(DECISION_URL, json=body, headers={"x-goog-api-key": self.key})
        r.latency_ms += (time.perf_counter() - t0) * 1000
        resp.raise_for_status()
        data = resp.json()
        tokens = int(data.get("usage", {}).get("total_input_tokens") or 0)
        r.calls += 1
        r.input_tokens += tokens
        r.cost += tokens * PRICE["gemini-decision-1"][0] / 1e6
        return data["answers"]

    @staticmethod
    def _choice(options: dict[str, str]) -> dict:
        return {
            "type": "choice",
            "instructions": "Which species of bird is in the photo?",
            "criteria": {**options, "other": "A different species, not listed here"},
        }

    def run(self, image: str, jpeg_b64: str) -> Result:
        r = Result("none", False, False)
        bird_q = {"type": "noul", "instructions": "A bird is visible in the photo."}
        if self.combined:
            a = self._ask(jpeg_b64, {"bird": bird_q, "species": self._choice(SHORT)}, r)
            p_bird = a["bird"]["noul"]
            r.steps.append(f"bird={p_bird:.2f}")
            species = a["species"]["choice"] if p_bird >= BIRD_THRESHOLD else None
            if species:
                r.steps.append(f"short={species}({a['species']['confidence']:.2f})")
        else:
            a = self._ask(jpeg_b64, {"bird": bird_q}, r)
            p_bird = a["bird"]["noul"]
            r.steps.append(f"bird={p_bird:.2f}")
            species = None
            if p_bird >= BIRD_THRESHOLD:
                a = self._ask(jpeg_b64, {"species": self._choice(SHORT)}, r)
                species = a["species"]["choice"]
                r.steps.append(f"short={species}({a['species']['confidence']:.2f})")
        if species == "other":
            a = self._ask(jpeg_b64, {"species": self._choice(WIDE)}, r)
            species = a["species"]["choice"]
            r.steps.append(f"wide={species}({a['species']['confidence']:.2f})")
        if species == "other":
            species = "unknown_bird"
        r.verdict = species or "none"
        r.correct_detection, r.correct_species = grade(image, species)
        return r


class AzureLLM:
    def __init__(self, base: str, key: str, deployment: str):
        self.url = base.rstrip("/") + "/chat/completions"
        self.key = key
        self.deployment = deployment
        self.name = f"llm {deployment} (1 call, free text)"
        self.client = httpx.Client(timeout=120)

    def run(self, image: str, jpeg_b64: str) -> Result:
        r = Result("", False, False)
        body = {
            "model": self.deployment,
            "messages": [
                {
                    "role": "user",
                    "content": [
                        {"type": "text", "text": LLM_PROMPT},
                        {
                            "type": "image_url",
                            "image_url": {"url": f"data:image/jpeg;base64,{jpeg_b64}"},
                        },
                    ],
                }
            ],
        }
        t0 = time.perf_counter()
        resp = self.client.post(self.url, json=body, headers={"api-key": self.key})
        r.latency_ms = (time.perf_counter() - t0) * 1000
        resp.raise_for_status()
        data = resp.json()
        text = data["choices"][0]["message"]["content"] or ""
        usage = data.get("usage") or {}
        r.calls = 1
        r.input_tokens = int(usage.get("prompt_tokens") or 0)
        r.output_tokens = int(usage.get("completion_tokens") or 0)  # includes reasoning tokens
        pin, pout = PRICE.get(self.deployment, (0.0, 0.0))
        r.cost = (r.input_tokens * pin + r.output_tokens * pout) / 1e6
        r.verdict = text.strip().replace("\n", " ")[:60]
        r.correct_detection, r.correct_species = grade_llm(image, text)
        return r


class LocalZeroShot:
    """Same 3 steps with a free local CLIP-style model. No 'no bird' class exists in these
    models, so step 1 picks between 'bird' and a few generic non-bird categories."""

    STEP1 = [
        "a photo of a bird",
        "a photo of a mammal",
        "a photo of a plant or flower",
        "a photo of an object",
        "a photo of a landscape",
        "a photo of a person",
    ]

    def __init__(self, model: str):
        import torch
        from transformers import pipeline

        device = "mps" if torch.backends.mps.is_available() else "cpu"
        t0 = time.perf_counter()
        self.pipe = pipeline("zero-shot-image-classification", model=model, device=device)
        self.load_s = time.perf_counter() - t0
        self.name = f"local {model.split('/')[-1]} ({device}, free)"
        self.short = {k: f"a photo of a {v}" for k, v in SHORT.items()}
        self.short["other"] = "a photo of some other kind of bird"
        self.wide = {k: f"a photo of a {v}" for k, v in WIDE.items()}

    def _top(self, img, labels: dict[str, str], r: Result) -> tuple[str, float]:
        t0 = time.perf_counter()
        out = self.pipe(img, candidate_labels=list(labels.values()))
        r.latency_ms += (time.perf_counter() - t0) * 1000
        r.calls += 1
        best = out[0]
        key = next(k for k, v in labels.items() if v == best["label"])
        return key, best["score"]

    def run(self, image: str, img) -> Result:
        r = Result("none", False, False)
        step1 = {str(i): label for i, label in enumerate(self.STEP1)}
        k, s = self._top(img, step1, r)
        is_bird = k == "0"
        r.steps.append(f"{'bird' if is_bird else 'not-bird'}({s:.2f})")
        species = None
        if is_bird:
            species, s = self._top(img, self.short, r)
            r.steps.append(f"short={species}({s:.2f})")
            if species == "other":
                species, s = self._top(img, self.wide, r)
                r.steps.append(f"wide={species}({s:.2f})")
        r.verdict = species or "none"
        r.correct_detection, r.correct_species = grade(image, species)
        return r


# -- runner ------------------------------------------------------------------------------------


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("images", type=Path)
    ap.add_argument("--repeats", type=int, default=3)
    ap.add_argument("--engines", default="decision,decision+,llm,local")
    ap.add_argument(
        "--local-models", default="openai/clip-vit-base-patch32,google/siglip-base-patch16-224"
    )
    ap.add_argument("--json", type=Path, default=Path("bird-results.json"))
    args = ap.parse_args()

    files = sorted(p for p in args.images.glob("*.jpg") if p.stem in TRUTH)
    imgs = {p.stem: p.read_bytes() for p in files}
    wanted = args.engines.split(",")
    engines: list = []
    if "decision" in wanted:
        engines.append(Decision(os.environ["GEMINI_DECISIONS_KEY"], combined=False))
    if "decision+" in wanted:
        engines.append(Decision(os.environ["GEMINI_DECISIONS_KEY"], combined=True))
    if "llm" in wanted:
        for dep in os.environ.get("AZ_DEPLOYMENTS", "gpt-5.4-mini").split(","):
            engines.append(AzureLLM(os.environ["AZ_BASE"], os.environ["AZ_KEY"], dep.strip()))
    if "local" in wanted:
        for m in args.local_models.split(","):
            engines.append(LocalZeroShot(m.strip()))

    report = {}
    for eng in engines:
        print(f"\n## {eng.name}", flush=True)
        if isinstance(eng, LocalZeroShot):
            import io

            from PIL import Image

            print(f"   model load: {eng.load_s:.1f}s (one-off)")
            inputs = {k: Image.open(io.BytesIO(v)).convert("RGB") for k, v in imgs.items()}
            eng.run("zebra", inputs["zebra"])  # warm-up, not timed
        else:
            inputs = {k: base64.b64encode(v).decode() for k, v in imgs.items()}
        rows = []
        for name in sorted(inputs):
            runs = [eng.run(name, inputs[name]) for _ in range(args.repeats)]
            first = runs[0]
            row = {
                "image": name,
                "verdict": first.verdict,
                "steps": " ".join(first.steps),
                "detect_ok": sum(r.correct_detection for r in runs) / len(runs),
                "species_ok": sum(r.correct_species for r in runs) / len(runs),
                "calls": statistics.mean(r.calls for r in runs),
                "in_tok": statistics.mean(r.input_tokens for r in runs),
                "out_tok": statistics.mean(r.output_tokens for r in runs),
                "cost": statistics.mean(r.cost for r in runs),
                "latency_ms": statistics.median(r.latency_ms for r in runs),
            }
            rows.append(row)
            mark = "✓" if row["species_ok"] == 1 else ("~" if row["species_ok"] > 0 else "✗")
            print(
                f"   {mark} {name:<10} {row['verdict']:<34} {row['latency_ms']:7.0f}ms "
                f"calls={row['calls']:.0f} in={row['in_tok']:.0f} out={row['out_tok']:.0f} "
                f"${row['cost']:.6f}  [{row['steps']}]",
                flush=True,
            )
        n = len(rows)
        summary = {
            "detection_acc": sum(r["detect_ok"] for r in rows) / n,
            "species_acc": sum(r["species_ok"] for r in rows) / n,
            "median_latency_ms": statistics.median(r["latency_ms"] for r in rows),
            "mean_latency_ms": statistics.mean(r["latency_ms"] for r in rows),
            "cost_per_image": sum(r["cost"] for r in rows) / n,
            "cost_per_1000": 1000 * sum(r["cost"] for r in rows) / n,
            "tokens_per_image": sum(r["in_tok"] + r["out_tok"] for r in rows) / n,
        }
        print(
            f"   => detection {summary['detection_acc']:.0%}  species {summary['species_acc']:.0%}"
            f"  median {summary['median_latency_ms']:.0f}ms/image"
            f"  ${summary['cost_per_1000']:.3f} per 1,000 images"
        )
        report[eng.name] = {"summary": summary, "rows": rows}
    args.json.write_text(json.dumps(report, indent=2))
    print(f"\nwrote {args.json}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
