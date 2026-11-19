"""End-to-end: the real CLI, real capture/decoding, real HTTP to the local fake server."""

from __future__ import annotations

import json
import subprocess
import sys
import time
from pathlib import Path

import pytest

from ifseen.cli import main


def run_cli(args, env, cwd=None):
    proc = subprocess.run(
        [sys.executable, "-m", "ifseen", *args],
        capture_output=True,
        text=True,
        env=env,
        cwd=cwd,
        timeout=60,
    )
    return proc


@pytest.fixture
def env(fake_server, monkeypatch):
    import os

    e = {
        k: v
        for k, v in os.environ.items()
        if not k.startswith(("GEMINI", "GOOGLE_API", "TYPESAFE", "AZURE_DECISION", "OPENAI"))
    }
    e["GEMINI_API_KEY"] = "test-key"
    return e


def test_oneliner_watch_video_fires_when_red_appears(
    fake_server, env, blue_then_red_video, tmp_path
):
    marker = tmp_path / "fired.txt"
    rules = tmp_path / "rules.yaml"
    rules.write_text(f"""
source:
  file: {{path: {blue_then_red_video}, realtime: false}}
every: 500ms
provider:
  name: gemini
  base_url: {fake_server.url}/v1beta/decisions
rules:
  - name: went-red
    when: The frame is mostly red.
    for: 2
    then:
      - shell: {{cmd: 'echo "$IFSEEN_RULE" >> {marker}', wait: true}}
      - exit
""")
    proc = run_cli(["watch", str(rules), "--json"], env)
    assert proc.returncode == 0, proc.stderr
    events = [json.loads(line) for line in proc.stdout.splitlines()]
    kinds = [e["event"] for e in events]
    assert kinds[0] == "start" and kinds[-1] == "stop"
    fires = [e for e in events if e["event"] == "fire"]
    assert [f["rule"] for f in fires] == ["went-red"]
    decisions = [e for e in events if e["event"] == "decision"]
    # the first 2s are blue: unchanged blue frames are skipped, so the API is called once
    # for blue and again only when the picture turns red
    assert decisions[0]["probs"]["went-red"] < 0.1
    assert decisions[-1]["probs"]["went-red"] > 0.9
    assert len(decisions) <= 3
    assert events[-1]["reason"] == "rule 'went-red' fired"
    assert marker.read_text().strip() == "went-red"


def test_oneliner_against_image(fake_server, env, red_png):
    proc = run_cli(
        [
            "The image is mostly red.",
            "The image is mostly green.",
            "--file",
            str(red_png),
            "--base-url",
            f"{fake_server.url}/v1beta/decisions",
            "--provider",
            "gemini",
            "--json",
            "--once",
            "--every",
            "200ms",
            "--max-ticks",
            "5",
        ],
        env,
    )
    assert proc.returncode == 0, proc.stderr
    events = [json.loads(line) for line in proc.stdout.splitlines()]
    assert [e["rule"] for e in events if e["event"] == "fire"] == ["the-image-is-mostly-red"]
    # identical frames: one API call, the rest skipped... but --once exits on the first fire
    assert len([e for e in events if e["event"] == "decision"]) == 1


def test_test_command_prints_probabilities(fake_server, env, blue_png, tmp_path):
    rules = tmp_path / "r.yaml"
    rules.write_text("""
source: screen
rules:
  - {name: blue, when: The picture is mostly blue., threshold: 0.7}
  - {name: red, when: The picture is mostly red.}
""")
    proc = run_cli(
        [
            "test",
            str(rules),
            "--image",
            str(blue_png),
            "--json",
            "--base-url",
            f"{fake_server.url}/v1beta/decisions",
        ],
        env,
    )
    assert proc.returncode == 0, proc.stderr
    out = json.loads(proc.stdout)
    assert out["probs"]["blue"] > 0.9 and out["probs"]["red"] < 0.1
    human = run_cli(
        [
            "test",
            str(rules),
            "--image",
            str(blue_png),
            "--base-url",
            f"{fake_server.url}/v1beta/decisions",
        ],
        env,
    )
    assert "would fire" in human.stdout and "yes" in human.stdout


def test_jev_style_server_via_systemone(fake_server, env, red_png):
    env = {**env, "TYPESAFE_API_KEY": "test-key"}
    proc = run_cli(
        [
            "The frame is mostly red.",
            "--file",
            str(red_png),
            "--provider",
            "systemone",
            "--base-url",
            fake_server.url,
            "--json",
            "--once",
            "--max-ticks",
            "3",
        ],
        env,
    )
    assert proc.returncode == 0, proc.stderr
    assert '"event": "fire"' in proc.stdout
    req = next(r for r in fake_server.requests if r["path"].endswith("/systemone"))
    assert req["body"]["assets"]


def test_missing_key_gives_helpful_error(env, red_png):
    env = {k: v for k, v in env.items() if k != "GEMINI_API_KEY"}
    proc = run_cli(["anything", "--file", str(red_png)], env)
    assert proc.returncode == 2
    assert "GEMINI_API_KEY" in proc.stderr and "--dry-run" in proc.stderr


def test_audio_source_needs_gemini(env, tmp_path):
    from ifseen.media import pcm16_to_wav

    wav = tmp_path / "a.wav"
    wav.write_bytes(pcm16_to_wav(b"\x00\x10" * 16000, 16000))
    env = {**env, "TYPESAFE_API_KEY": "k"}
    proc = run_cli(["a dog barks", "--file", str(wav), "--provider", "jev"], env)
    assert proc.returncode == 2 and "audio" in proc.stderr


def test_dry_run_needs_no_key(env, red_png):
    env = {k: v for k, v in env.items() if k != "GEMINI_API_KEY"}
    proc = run_cli(
        [
            "something",
            "--file",
            str(red_png),
            "--dry-run",
            "--plain",
            "--max-ticks",
            "3",
            "--every",
            "100ms",
        ],
        env,
    )
    assert proc.returncode == 0, proc.stderr
    assert "dry run" in proc.stdout


def test_recipes_and_init(tmp_path, capsys):
    assert main(["recipes"]) == 0
    assert "doorbell" in capsys.readouterr().out
    assert main(["recipes", "doorbell"]) == 0
    assert "person-at-door" in capsys.readouterr().out
    out = tmp_path / "mine.yaml"
    assert main(["init", "kitchen", "-o", str(out)]) == 0
    assert out.exists()
    assert main(["init", "kitchen", "-o", str(out)]) == 2  # refuses to overwrite


def test_unknown_recipe(capsys):
    assert main(["watch", "definitely-not-a-recipe"]) == 2
    assert "no such file or recipe" in capsys.readouterr().err


def test_version(capsys):
    assert main(["--version"]) == 0
    assert capsys.readouterr().out.startswith("ifseen ")


def test_oneliner_config_builder():
    import argparse

    from ifseen.cli import build_oneliner_config

    ns = argparse.Namespace(
        conditions=["Kettle is boiling!", "Kettle is boiling!"],
        camera="0",
        url=None,
        file=None,
        screen=None,
        mic=True,
        then=["say hi"],
        notify=True,
        say=None,
        ntfy="t",
        webhook=None,
        snapshot=None,
        once=True,
        threshold=0.7,
        consecutive=2,
        cooldown="10s",
        context=None,
        prefilter=None,
    )
    data = build_oneliner_config(ns)
    assert data["source"] == {"camera": "0", "mic": {}}
    names = [r["name"] for r in data["rules"]]
    assert names == ["kettle-is-boiling", "kettle-is-boiling-2"]
    assert data["rules"][0]["then"] == [{"shell": "say hi"}, "notify", {"ntfy": "t"}, "exit"]
    assert data["rules"][0]["for"] == 2
    assert "prefilter" not in data
    ns.prefilter = "A kettle is visible."
    assert build_oneliner_config(ns)["prefilter"] == {
        "provider": "local",
        "when": "A kettle is visible.",
    }


def test_package_ships_recipes():
    import ifseen.recipes as r

    assert any(p.name.endswith(".yaml") for p in Path(r.__file__).parent.iterdir())


def test_subcommand_typos_are_caught(capsys):
    assert main(["recipe"]) == 2
    assert "did you mean" in capsys.readouterr().err


def test_bad_screen_number_is_a_usage_error(capsys):
    with pytest.raises(SystemExit) as exc:
        main(["something", "--screen", "abc"])
    assert exc.value.code == 2


def test_unreadable_image_fails_cleanly(env, tmp_path):
    bad = tmp_path / "broken.png"
    bad.write_bytes(b"not a png")
    proc = run_cli(["test", "build-watcher", "--image", str(bad)], env)
    assert proc.returncode == 2
    assert "could not read broken.png" in proc.stderr
    assert "Traceback" not in proc.stderr


def test_bad_wav_in_test_command_fails_cleanly(env, red_png, tmp_path):
    bad = tmp_path / "bad.wav"
    bad.write_bytes(b"RIFF nope")
    proc = run_cli(["test", "build-watcher", "--image", str(red_png), "--audio", str(bad)], env)
    assert proc.returncode == 2 and "PCM WAV" in proc.stderr
    assert "Traceback" not in proc.stderr


def test_prefilter_gates_the_main_provider(fake_server, env, red_png, tmp_path):
    rules = tmp_path / "r.yaml"
    rules.write_text(f"""
source: {{file: {red_png}}}
every: 200ms
provider: {{name: gemini, base_url: {fake_server.url}/v1beta/decisions}}
prefilter:
  provider: {{name: gemini, base_url: {fake_server.url}/v1beta/decisions}}
  when: The frame is mostly blue.
rules:
  - {{name: red, when: The frame is mostly red.}}
""")
    proc = run_cli(["watch", str(rules), "--json", "--max-ticks", "1"], env)
    assert proc.returncode == 0, proc.stderr
    events = [json.loads(line) for line in proc.stdout.splitlines()]
    assert events[0]["prefilter"].startswith("gemini")
    decision = next(e for e in events if e["event"] == "decision")
    assert decision["skipped"] == "prefilter" and decision["probs"] == {"red": 0.0}

    test = run_cli(["test", str(rules), "--image", str(red_png)], env)
    assert test.returncode == 0, test.stderr
    assert "main provider would be skipped" in " ".join(test.stdout.split())


def test_dry_run_swaps_the_prefilter_for_mock(env, red_png, tmp_path):
    rules = tmp_path / "r.yaml"
    rules.write_text(f"""
source: {{file: {red_png}}}
prefilter: {{provider: gemini, when: A person is visible.}}
rules:
  - {{name: red, when: The frame is mostly red.}}
""")
    env = {k: v for k, v in env.items() if k != "GEMINI_API_KEY"}
    proc = run_cli(["watch", str(rules), "--dry-run", "--json", "--max-ticks", "1"], env)
    assert proc.returncode == 0, proc.stderr
    events = [json.loads(line) for line in proc.stdout.splitlines()]
    start = next(e for e in events if e["event"] == "start")
    assert start["prefilter"].startswith("mock")


def test_image_only_prefilter_rejects_mic_only_source(env, tmp_path):
    import wave

    clip = tmp_path / "a.wav"
    with wave.open(str(clip), "wb") as w:
        w.setnchannels(1)
        w.setsampwidth(2)
        w.setframerate(16000)
        w.writeframes(b"\x10\x00" * 16000)
    rules = tmp_path / "r.yaml"
    rules.write_text(f"""
source: {{file: {clip}}}
provider: gemini
prefilter: {{provider: {{name: openai, model: m, base_url: http://127.0.0.1:9}}, when: x}}
rules:
  - {{name: r, when: someone speaks}}
""")
    proc = run_cli(["watch", str(rules), "--json", "--max-ticks", "1"], env)
    assert proc.returncode == 2
    assert "prefilter provider openai can't handle audio" in proc.stderr


def test_sigterm_is_treated_like_ctrl_c():
    import os
    import signal

    from ifseen.cli import _sigterm_as_interrupt

    previous = signal.getsignal(signal.SIGTERM)
    try:
        _sigterm_as_interrupt()
        with pytest.raises(KeyboardInterrupt):
            os.kill(os.getpid(), signal.SIGTERM)
            time.sleep(1)  # the handler runs between bytecodes; never reached
    finally:
        signal.signal(signal.SIGTERM, previous)
