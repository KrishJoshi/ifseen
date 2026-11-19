"""Synthetic screenshots for the hard-rules benchmark: CI pages and app windows/dialogs.

Each screenshot is drawn with PIL in one of several layouts so no single template dominates.

    python benchmarks/hard_rules_screens.py OUT_DIR
"""

from __future__ import annotations

import sys
from pathlib import Path

from PIL import Image, ImageDraw, ImageFont

W, H = 1280, 800
FONT_PATHS = {
    "sans": ["/System/Library/Fonts/Helvetica.ttc", "DejaVuSans.ttf"],
    "mono": ["/System/Library/Fonts/Menlo.ttc", "DejaVuSansMono.ttf"],
}
GREEN, RED, AMBER, GREY = (31, 136, 61), (207, 34, 46), (191, 135, 0), (110, 118, 129)


def font(size: int, kind: str = "sans") -> ImageFont.FreeTypeFont:
    for path in FONT_PATHS[kind]:
        try:
            return ImageFont.truetype(path, size)
        except OSError:
            continue
    return ImageFont.load_default(size)


def icon(d: ImageDraw.ImageDraw, x: int, y: int, state: str, r: int = 9) -> None:
    color = {"ok": GREEN, "fail": RED, "run": AMBER, "skip": GREY}[state]
    if state == "run":
        d.ellipse((x - r, y - r, x + r, y + r), outline=color, width=3)
        d.arc((x - r, y - r, x + r, y + r), 0, 90, fill=(255, 255, 255), width=3)
        return
    d.ellipse((x - r, y - r, x + r, y + r), fill=color)
    if state == "ok":
        d.line((x - 4, y, x - 1, y + 4, x + 5, y - 4), fill="white", width=2)
    elif state == "fail":
        d.line((x - 4, y - 4, x + 4, y + 4), fill="white", width=2)
        d.line((x - 4, y + 4, x + 4, y - 4), fill="white", width=2)


def browser(title: str, url: str, dark: bool = False) -> tuple[Image.Image, ImageDraw.ImageDraw]:
    bg = (13, 17, 23) if dark else (255, 255, 255)
    img = Image.new("RGB", (W, H), bg)
    d = ImageDraw.Draw(img)
    d.rectangle((0, 0, W, 72), fill=(222, 225, 230) if not dark else (36, 41, 47))
    for i, c in enumerate([(255, 95, 86), (255, 189, 46), (39, 201, 63)]):
        d.ellipse((14 + i * 22, 12, 26 + i * 22, 24), fill=c)
    d.rounded_rectangle((90, 6, 330, 32), 6, fill=bg)
    d.text((102, 11), title[:30], font=font(13), fill=(90, 90, 90) if not dark else (200,) * 3)
    d.rounded_rectangle(
        (90, 40, W - 20, 66), 12, fill=(255, 255, 255) if not dark else (22, 27, 34)
    )
    d.text((106, 45), url, font=font(14), fill=(80, 80, 80) if not dark else (170,) * 3)
    return img, d


def github_actions(overall: str, jobs: list[tuple[str, str, str]], dark: bool = False):
    img, d = browser("Actions · acme/api", "github.com/acme/api/actions/runs/8812345", dark)
    fg = (230, 237, 243) if dark else (31, 35, 40)
    d.rectangle((0, 72, W, 120), fill=(246, 248, 250) if not dark else (22, 27, 34))
    d.text((24, 86), "acme / api", font=font(18), fill=fg)
    head = {"fail": "failed", "ok": "succeeded", "run": "in progress"}[overall]
    icon(d, 36, 150, overall, 12)
    d.text((58, 137), f"fix: retry flaky upload  #4821  - {head}", font=font(24), fill=fg)
    d.text((58, 172), "CI  ·  main  ·  triggered via push 4 minutes ago", font=font(14), fill=GREY)
    d.rectangle((24, 210, 300, 760), outline=(208, 215, 222), width=1)
    d.text((40, 222), "Jobs", font=font(15), fill=GREY)
    y = 256
    for name, state, dur in jobs:
        icon(d, 46, y + 10, state)
        d.text((66, y), name, font=font(15), fill=fg)
        d.text((240, y), dur, font=font(13), fill=GREY)
        y += 38
    d.rectangle((320, 210, W - 24, 760), outline=(208, 215, 222), width=1)
    status = {"fail": ("Failure", RED), "ok": ("Success", GREEN), "run": ("In progress", AMBER)}
    label, color = status[overall]
    d.text((340, 226), "Status", font=font(13), fill=GREY)
    d.text((340, 246), label, font=font(20), fill=color)
    d.text((520, 226), "Total duration", font=font(13), fill=GREY)
    d.text((520, 246), "3m 41s" if overall != "run" else "-", font=font(20), fill=fg)
    if overall == "fail":
        d.rounded_rectangle((340, 300, W - 44, 380), 6, outline=RED, width=1)
        d.text((356, 312), "Annotations", font=font(15), fill=fg)
        d.text(
            (356, 340),
            "x  test (3.12): Process completed with exit code 1.",
            font=font(14),
            fill=RED,
        )
    return img


def gitlab_pipeline(overall: str, stages: list[list[tuple[str, str]]]):
    img, d = browser("Pipeline · GitLab", "gitlab.example.com/platform/web/-/pipelines/99231")
    d.rectangle((0, 72, 220, H), fill=(251, 250, 253))
    for i, item in enumerate(["Project", "Code", "Build", "Pipelines", "Jobs", "Deploy"]):
        d.text((24, 100 + i * 34), item, font=font(15), fill=(83, 81, 88))
    badge = {"fail": ("failed", RED), "ok": ("passed", GREEN), "run": ("running", (31, 117, 203))}
    text, color = badge[overall]
    d.rounded_rectangle((250, 100, 350, 128), 12, fill=color)
    d.text((268, 104), text, font=font(16), fill="white")
    d.text(
        (366, 104),
        "Pipeline #99231 triggered 2 minutes ago by Dana",
        font=font(16),
        fill=(40, 40, 40),
    )
    d.text((250, 150), "Update dependency eslint to v9", font=font(26), fill=(30, 30, 30))
    names = ["build", "test", "deploy"]
    for si, stage in enumerate(stages):
        x = 260 + si * 300
        d.text((x, 220), names[si], font=font(15), fill=GREY)
        for ji, (job, state) in enumerate(stage):
            y = 256 + ji * 52
            d.rounded_rectangle((x, y, x + 240, y + 40), 20, outline=(220, 220, 225), width=2)
            icon(d, x + 22, y + 20, state if state != "run" else "run")
            d.text((x + 42, y + 11), job, font=font(15), fill=(40, 40, 40))
    return img


def jenkins(overall: str):
    img, d = browser("Jenkins", "ci.internal/job/payments-service/1287/")
    d.rectangle((0, 72, W, 120), fill=(0, 0, 0))
    d.text((24, 84), "Jenkins", font=font(22), fill="white")
    color = {"fail": RED, "ok": GREEN, "run": (100, 150, 220)}[overall]
    word = {"fail": "FAILURE", "ok": "SUCCESS", "run": "BUILDING"}[overall]
    d.ellipse((40, 150, 80, 190), fill=color)
    d.text((100, 152), f"Build #1287 ({word})", font=font(30), fill=(30, 30, 30))
    d.text((100, 200), "Started by GitHub push by kai", font=font(15), fill=GREY)
    d.rectangle((40, 250, W - 40, 740), fill=(250, 250, 250), outline=(220, 220, 220))
    log = [
        "[Pipeline] stage (Test)",
        "+ ./gradlew test",
        "> Task :compileJava UP-TO-DATE",
    ]
    if overall == "fail":
        log += [
            "PaymentServiceTest > refundsPartial() FAILED",
            "    java.lang.AssertionError at PaymentServiceTest.java:88",
            "42 tests completed, 1 failed",
            "BUILD FAILED in 1m 12s",
            "Finished: FAILURE",
        ]
    elif overall == "ok":
        log += ["42 tests completed", "BUILD SUCCESSFUL in 1m 09s", "Finished: SUCCESS"]
    else:
        log += ["> Task :test", "  31 of 42 tests completed..."]
    for i, line in enumerate(log):
        fill = RED if "FAIL" in line else GREEN if "SUCCESS" in line else (50, 50, 50)
        d.text((60, 270 + i * 26), line, font=font(16, "mono"), fill=fill)
    return img


def terminal(overall: str):
    img = Image.new("RGB", (W, H), (30, 30, 30))
    d = ImageDraw.Draw(img)
    d.rectangle((0, 0, W, 28), fill=(56, 56, 56))
    d.text((W // 2 - 80, 6), "zsh - make ci", font=font(13), fill=(200, 200, 200))
    lines = [
        ("$ make ci", (220, 220, 220)),
        ("ruff check src tests ... ok", (180, 180, 180)),
        ("pytest -q", (180, 180, 180)),
        ("........................................................ [ 72%]", (180, 180, 180)),
    ]
    if overall == "fail":
        lines += [
            ("..........F.......                                       [100%]", (180, 180, 180)),
            ("FAILED tests/test_sync.py::test_resume_after_crash - KeyError", (240, 80, 80)),
            ("1 failed, 211 passed in 9.81s", (240, 80, 80)),
            ("make: *** [ci] Error 1", (240, 80, 80)),
            ("CI FAILED", (240, 80, 80)),
        ]
    elif overall == "ok":
        lines += [
            ("..................                                       [100%]", (180, 180, 180)),
            ("212 passed in 9.42s", (80, 220, 100)),
            ("CI passed", (80, 220, 100)),
        ]
    else:
        lines += [("....", (180, 180, 180))]
    for i, (text, color) in enumerate(lines):
        d.text((20, 44 + i * 26), text, font=font(17, "mono"), fill=color)
    return img


def editor(dark: bool = True) -> Image.Image:
    bg = (30, 31, 34) if dark else (250, 250, 250)
    img = Image.new("RGB", (W, H), bg)
    d = ImageDraw.Draw(img)
    d.rectangle((0, 0, W, 30), fill=(43, 45, 48) if dark else (230, 230, 230))
    d.rectangle((0, 30, 240, H), fill=(37, 38, 41) if dark else (240, 240, 240))
    for i, f in enumerate(["src/", "  app.py", "  models.py", "  views.py", "tests/", "README.md"]):
        d.text((16, 50 + i * 24), f, font=font(14), fill=(180, 180, 180) if dark else (60,) * 3)
    code = [
        "def handle(request):",
        "    user = authenticate(request)",
        "    if not user:",
        "        return redirect('/login')",
        "    items = Item.objects.filter(owner=user)",
        "    return render(request, 'items.html', {'items': items})",
    ]
    for i, line in enumerate(code):
        d.text(
            (270, 50 + i * 24),
            f"{i + 1:>3}  {line}",
            font=font(15, "mono"),
            fill=(200, 200, 200) if dark else (40, 40, 40),
        )
    return img


def mail_app() -> Image.Image:
    img = Image.new("RGB", (W, H), (255, 255, 255))
    d = ImageDraw.Draw(img)
    d.rectangle((0, 0, W, 50), fill=(0, 120, 212))
    d.text((20, 14), "Outlook", font=font(20), fill="white")
    d.rectangle((0, 50, 300, H), fill=(243, 242, 241))
    for i, m in enumerate(
        ["Lunch on Friday?", "Q3 planning notes", "Invoice #2231", "Re: offsite"]
    ):
        d.text((20, 70 + i * 60), m, font=font(16), fill=(30, 30, 30))
        d.text((20, 92 + i * 60), "Hi team, quick update on...", font=font(13), fill=GREY)
    d.text((330, 80), "Q3 planning notes", font=font(26), fill=(30, 30, 30))
    body = [
        "Hi all,",
        "",
        "Attached are the notes from today's planning session.",
        "Let me know if I missed anything.",
        "",
        "Thanks, Priya",
    ]
    for i, line in enumerate(body):
        d.text((330, 140 + i * 26), line, font=font(16), fill=(50, 50, 50))
    return img


def dialog(base: Image.Image, title: str, message: str, style: str, kind: str) -> Image.Image:
    img = base.copy()
    over = Image.new("RGBA", img.size, (0, 0, 0, 90))
    img = Image.alpha_composite(img.convert("RGBA"), over).convert("RGB")
    d = ImageDraw.Draw(img)
    bw, bh = 520, 220
    x0, y0 = (W - bw) // 2, (H - bh) // 2
    if style == "mac":
        d.rounded_rectangle((x0, y0, x0 + bw, y0 + bh), 14, fill=(236, 236, 236))
        cx = x0 + 50
        if kind == "error":
            d.polygon([(cx, y0 + 30), (cx - 26, y0 + 76), (cx + 26, y0 + 76)], fill=(250, 200, 0))
            d.text((cx - 4, y0 + 44), "!", font=font(28), fill=(20, 20, 20))
        else:
            d.ellipse((cx - 24, y0 + 30, cx + 24, y0 + 78), fill=(0, 122, 255))
            d.text((cx - 4, y0 + 38), "i", font=font(28), fill="white")
        d.text((x0 + 100, y0 + 30), title, font=font(18), fill=(20, 20, 20))
        for i, line in enumerate(message.split("\n")):
            d.text((x0 + 100, y0 + 62 + i * 22), line, font=font(14), fill=(60, 60, 60))
        d.rounded_rectangle(
            (x0 + bw - 120, y0 + bh - 50, x0 + bw - 20, y0 + bh - 20), 6, fill=(0, 122, 255)
        )
        d.text((x0 + bw - 88, y0 + bh - 45), "OK", font=font(15), fill="white")
    else:  # windows
        d.rectangle((x0, y0, x0 + bw, y0 + bh), fill=(255, 255, 255), outline=(120, 120, 120))
        d.rectangle((x0, y0, x0 + bw, y0 + 32), fill=(240, 240, 240))
        d.text((x0 + 12, y0 + 8), title, font=font(14), fill=(20, 20, 20))
        cx, cy = x0 + 50, y0 + 90
        if kind == "error":
            d.ellipse((cx - 22, cy - 22, cx + 22, cy + 22), fill=(232, 17, 35))
            d.line((cx - 9, cy - 9, cx + 9, cy + 9), fill="white", width=4)
            d.line((cx - 9, cy + 9, cx + 9, cy - 9), fill="white", width=4)
        else:
            d.ellipse((cx - 22, cy - 22, cx + 22, cy + 22), fill=(0, 103, 192))
            d.text((cx - 4, cy - 16), "?", font=font(26), fill="white")
        for i, line in enumerate(message.split("\n")):
            d.text((x0 + 90, y0 + 70 + i * 22), line, font=font(15), fill=(30, 30, 30))
        labels = ["OK"] if kind == "error" else ["Save", "Don't Save"]
        for i, lab in enumerate(labels):
            bx = x0 + bw - 110 - i * 110
            d.rectangle((bx, y0 + bh - 46, bx + 96, y0 + bh - 18), outline=(0, 103, 192), width=2)
            d.text((bx + 20, y0 + bh - 41), lab, font=font(14), fill=(20, 20, 20))
    return img


def browser_error_banner() -> Image.Image:
    img, d = browser("Checkout", "shop.example.com/checkout")
    d.text((60, 120), "Checkout", font=font(32), fill=(30, 30, 30))
    for i, f in enumerate(["Name", "Card number", "Expiry"]):
        d.text((60, 190 + i * 70), f, font=font(15), fill=GREY)
        d.rectangle((60, 212 + i * 70, 600, 244 + i * 70), outline=(200, 200, 200))
    return dialog(
        img,
        "Error",
        "Payment failed: the server returned an\nunexpected error (500). Please try again.",
        "mac",
        "error",
    )


# name -> (image, truth set)
def screens() -> dict[str, tuple[Image.Image, set[str]]]:
    gh_fail = [
        ("lint", "ok", "21s"),
        ("test (3.11)", "ok", "2m 2s"),
        ("test (3.12)", "fail", "1m 58s"),
        ("build", "skip", "-"),
    ]
    gh_ok = [
        ("lint", "ok", "19s"),
        ("test (3.11)", "ok", "2m 1s"),
        ("test (3.12)", "ok", "2m 4s"),
        ("build", "ok", "48s"),
    ]
    gh_run = [
        ("lint", "ok", "20s"),
        ("test (3.11)", "run", "1m 3s"),
        ("test (3.12)", "run", "1m 1s"),
        ("build", "skip", "-"),
    ]
    gl = {
        "fail": [
            [("compile", "ok"), ("docker", "ok")],
            [("unit", "fail"), ("e2e", "ok")],
            [("staging", "skip")],
        ],
        "ok": [
            [("compile", "ok"), ("docker", "ok")],
            [("unit", "ok"), ("e2e", "ok")],
            [("staging", "ok")],
        ],
        "run": [
            [("compile", "ok"), ("docker", "ok")],
            [("unit", "run"), ("e2e", "run")],
            [("staging", "skip")],
        ],
    }
    ci_failed, err = {"ci_failed"}, {"error_dialog"}
    return {
        "ci_github_fail": (github_actions("fail", gh_fail), ci_failed),
        "ci_github_fail_dark": (github_actions("fail", gh_fail, dark=True), ci_failed),
        "ci_gitlab_fail": (gitlab_pipeline("fail", gl["fail"]), ci_failed),
        "ci_jenkins_fail": (jenkins("fail"), ci_failed),
        "ci_terminal_fail": (terminal("fail"), ci_failed),
        "ci_github_ok": (github_actions("ok", gh_ok), set()),
        "ci_gitlab_ok": (gitlab_pipeline("ok", gl["ok"]), set()),
        "ci_jenkins_ok": (jenkins("ok"), set()),
        "ci_terminal_ok": (terminal("ok"), set()),
        "ci_github_running": (github_actions("run", gh_run, dark=True), set()),
        "ci_gitlab_running": (gitlab_pipeline("run", gl["run"]), set()),
        "ci_jenkins_running": (jenkins("run"), set()),
        "dlg_editor_mac_error": (
            dialog(
                editor(),
                "The document could not be saved.",
                'You don\'t have permission to write to\n"app.py".',
                "mac",
                "error",
            ),
            err,
        ),
        "dlg_mail_win_error": (
            dialog(
                mail_app(),
                "Outlook",
                "Cannot connect to the server.\nError 0x800CCC0E.",
                "win",
                "error",
            ),
            err,
        ),
        "dlg_browser_error": (browser_error_banner(), err),
        "dlg_editor_win_error": (
            dialog(
                editor(dark=False),
                "Application Error",
                "The instruction at 0x00007ff6 referenced\nmemory that could not be read.",
                "win",
                "error",
            ),
            err,
        ),
        "app_editor_plain": (editor(), set()),
        "app_mail_plain": (mail_app(), set()),
        "dlg_editor_win_save": (
            dialog(
                editor(dark=False),
                "Notepad",
                "Do you want to save changes to\nnotes.txt?",
                "win",
                "question",
            ),
            set(),
        ),
        "dlg_mail_mac_info": (
            dialog(
                mail_app(),
                "Update available",
                "Version 16.2 is ready to install.\nIt will be applied on restart.",
                "mac",
                "info",
            ),
            set(),
        ),
    }


def main() -> int:
    out = Path(sys.argv[1] if len(sys.argv) > 1 else "/tmp/hard-rules/img")
    out.mkdir(parents=True, exist_ok=True)
    for name, (img, _) in screens().items():
        img.save(out / f"screen_{name}.jpg", quality=85)
    print(f"wrote {len(screens())} screenshots to {out}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
