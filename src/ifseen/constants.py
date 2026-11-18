"""Static defaults, endpoints and price tables."""

from __future__ import annotations

VERSION = "0.1.0"

DEFAULT_EVERY_SECONDS = 2.0
DEFAULT_THRESHOLD = 0.8
DEFAULT_CONSECUTIVE = 1
DEFAULT_COOLDOWN_SECONDS = 30.0
# A rule re-arms once its probability drops this far below its threshold.
DEFAULT_HYSTERESIS = 0.15

# Mean absolute pixel difference (0-255) on a 32x32 greyscale thumbnail below which
# a frame counts as "unchanged" and the previous answers are reused.
DEFAULT_CHANGE_THRESHOLD = 2.5
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
}

PROVIDER_NAMES = ("gemini", "jev", "azure", "systemone", "openai", "ollama", "mock")

NTFY_DEFAULT_SERVER = "https://ntfy.sh"

ACTION_KINDS = frozenset({"notify", "say", "shell", "webhook", "ntfy", "snapshot", "log", "exit"})
# Actions that may be written as a bare string with no options.
BARE_ACTIONS = frozenset({"notify", "log", "exit", "snapshot", "say"})
