"""Render the live dashboard to docs/dashboard.svg using scripted probabilities.

python scripts/render_dashboard_svg.py
"""

from __future__ import annotations

import io
import math
import time
from pathlib import Path

from PIL import Image
from rich.console import Console

from ifseen.actions import ActionRunner
from ifseen.config import load_config
from ifseen.engine import Engine
from ifseen.media import image_to_sample
from ifseen.providers import Decision, Provider
from ifseen.sources import Source
from ifseen.ui import Dashboard

TICKS = 40


def curve(i: int, name: str) -> float:
    if name == "person-at-door":
        return 0.04 + 0.9 * max(0.0, math.sin((i - 18) / 6)) if 18 <= i <= 36 else 0.05
    if name == "parcel-left":
        return min(0.97, 0.02 + max(0, i - 28) * 0.12)
    if name == "dog-in-garden":
        return 0.3 + 0.2 * math.sin(i / 3)
    return 0.03


class Scripted(Provider):
    name = "gemini"
    price_per_m_input = 0.10

    def __init__(self):
        super().__init__("gemini-decision-1")
        self.i = 0

    def decide(self, sample, questions, context=None):
        self.i += 1
        return Decision({q.key: curve(self.i, q.key) for q in questions}, 1290, 182.0)


class Frames(Source):
    kind = "url"
    provides = frozenset({"image"})

    def __init__(self):
        self.i = 0

    def read(self):
        self.i += 1
        return image_to_sample(Image.new("RGB", (640, 480), (self.i * 6 % 255, 80, 120)))

    def describe(self):
        return "url frigate.local/api/front_door/latest.jpg"


def main() -> None:
    cfg = load_config(
        {
            "source": "screen",
            "every": "2s",
            "skip_unchanged": False,
            "rules": [
                {
                    "name": "person-at-door",
                    "when": "A person is standing at or walking up to the front door.",
                    "for": 2,
                    "then": ["log"],
                },
                {
                    "name": "parcel-left",
                    "when": "A parcel or box has been left on the doorstep.",
                    "for": 3,
                    "then": ["log"],
                },
                {"name": "dog-in-garden", "when": "A dog is in the front garden.", "then": ["log"]},
                {"name": "door-open", "when": "The front door is standing open.", "then": ["log"]},
            ],
        }
    )
    console = Console(record=True, width=112, file=io.StringIO(), force_terminal=True)
    dash = Dashboard(console)
    t = [1_000.0]
    engine = Engine(
        cfg,
        Frames(),
        Scripted(),
        ActionRunner(log=dash.add, background=False),
        listener=dash,
        clock=lambda: t[0],
        sleep=lambda s: t.__setitem__(0, t[0] + s),
    )
    dash.attach(engine)
    engine.stats.started = time.time() - TICKS * 2
    dash(
        {
            "event": "start",
            "source": Frames().describe(),
            "provider": "gemini (gemini-decision-1)",
            "rules": [],
        }
    )
    for _ in range(TICKS):
        engine.tick()
    dash.log = type(dash.log)(
        [
            (ts, lvl, msg.replace("[person-at-door] ", "📸 ").replace("[parcel-left] ", "📸 "))
            for ts, lvl, msg in dash.log
        ],
        maxlen=dash.log.maxlen,
    )
    console.print(dash.render())
    out = Path(__file__).resolve().parent.parent / "docs" / "dashboard.svg"
    console.save_svg(str(out), title="ifseen watch doorbell")
    print(f"wrote {out}")


if __name__ == "__main__":
    main()
