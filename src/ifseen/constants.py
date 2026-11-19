"""Static defaults, endpoints and price tables."""

from __future__ import annotations

VERSION = "0.1.0"

DEFAULT_EVERY_SECONDS = 2.0
DEFAULT_THRESHOLD = 0.8
DEFAULT_CONSECUTIVE = 1
DEFAULT_COOLDOWN_SECONDS = 30.0
# A rule re-arms once its probability drops this far below its threshold.
DEFAULT_HYSTERESIS = 0.15

# A frame counts as "unchanged" (previous answers reused, no API call) when fewer than
# this percentage of thumbnail pixels changed noticeably. Colour matters: a status turning
# from green to red barely changes brightness, so a greyscale mean diff misses it.
DEFAULT_CHANGE_THRESHOLD = 0.25
CHANGE_THUMBNAIL_SIZE = 96
# Per-pixel change (0-255, any RGB channel) that counts as "noticeable" - above JPEG and
# sensor noise after downscaling.
CHANGE_PIXEL_DELTA = 32
# Even when nothing changes, re-ask at least this often.
DEFAULT_MAX_SKIP_SECONDS = 60.0
# RMS (int16 scale) below which an audio chunk counts as silence.
DEFAULT_SILENCE_RMS = 120.0

DEFAULT_MIC_SECONDS = 4.0
MIC_SAMPLE_RATE = 16_000

JPEG_QUALITY = 80
# System One (Jev) rejects images outside these bounds instead of resizing them.
IMAGE_MAX_SIDE = 1568
IMAGE_MIN_SIDE = 280

HTTP_TIMEOUT_SECONDS = 30.0

GEMINI_URL = "https://generativelanguage.googleapis.com/v1beta/decisions"
GEMINI_DEFAULT_MODEL = "gemini-decision-1"
GEMINI_KEY_ENVS = ("GEMINI_API_KEY", "GOOGLE_API_KEY")

JEV_URL = "https://api.typesafe.ai/v1/systemone"
JEV_DEFAULT_MODEL = "jev-latest"
JEV_KEY_ENV = "TYPESAFE_API_KEY"
JEV_IMAGE_HEADER = "TypeSafe-Danger-Zone-Images"

AZURE_ENDPOINT_ENV = "AZURE_DECISION_ENDPOINT"
AZURE_KEY_ENV = "AZURE_DECISION_KEY"
AZURE_DEPLOYMENT_ENV = "AZURE_DECISION_DEPLOYMENT"
AZURE_PATH = "/providers/microsoft/v1/systemone"
AZURE_DEFAULT_MODEL = "Microsoft-Decision-1.1"

OPENAI_DEFAULT_BASE = "https://api.openai.com/v1"
OPENAI_KEY_ENV = "OPENAI_API_KEY"
OPENAI_BASE_ENV = "OPENAI_BASE_URL"
OLLAMA_DEFAULT_BASE = "http://localhost:11434/v1"

# USD per 1M input tokens. Output tokens are free on all decision models.
PRICE_PER_M_INPUT = {
    "gemini": 0.10,
    "jev": 0.042,
    "azure": 0.042,
    "systemone": 0.0,
    "openai": 0.0,
    "ollama": 0.0,
    "mock": 0.0,
    "local": 0.0,
}

PROVIDER_NAMES = ("gemini", "jev", "azure", "systemone", "openai", "ollama", "local", "mock")

# Free offline zero-shot provider (`pip install 'ifseen[local]'`).
LOCAL_DEFAULT_MODEL = "google/siglip-base-patch16-224"
# Raw SigLIP match probabilities for true captions mostly sit around 0.01-0.3, so a rule
# without a contrast phrase is scored as sigmoid(logit + offset). 3.0 gave the best accuracy
# at a 0.5 threshold across the hard-rules benchmark; it's a starting point, not calibration.
LOCAL_SIGLIP_LOGIT_OFFSET = 3.0
# CLIP has no per-caption probability, so a rule without a contrast competes with these.
LOCAL_GENERIC_LABELS = (
    "a photo.",
    "a screenshot of a computer screen.",
    "a picture of something else.",
    "an everyday scene.",
)
LOCAL_MODULES = ("torch", "transformers")

NTFY_DEFAULT_SERVER = "https://ntfy.sh"

ACTION_KINDS = frozenset({"notify", "say", "shell", "webhook", "ntfy", "snapshot", "log", "exit"})
# Actions that may be written as a bare string with no options.
BARE_ACTIONS = frozenset({"notify", "log", "exit", "snapshot", "say"})

# Cascade: a cheap provider answers one gating question before the main provider is called.
# Deliberately permissive: a false pass costs one normal call, a false block misses an event.
# Local SigLIP presence scores ("A dog is visible.") were 0.02-0.5 when true and under 0.003
# when absent in the hard-rules benchmark, so 0.5 would block real events.
DEFAULT_PREFILTER_THRESHOLD = 0.05
PREFILTER_KEY = "__prefilter__"
PREFILTER_SKIP_REASON = "prefilter"
# Provider used by the one-liner's --prefilter flag: free, local and image-only.
PREFILTER_DEFAULT_PROVIDER = "local"
