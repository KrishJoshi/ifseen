# PyInstaller spec for the one-file `ifseen` binary.
#
#   pip install ".[all]" "pyinstaller>=6.11,<7"
#   pyinstaller packaging/ifseen.spec --noconfirm --clean
#   -> dist/ifseen (dist/ifseen.exe on Windows)
#
# Bundles the screen, camera, mic and mqtt extras when they're installed in the build env.
# The `local` provider (torch + transformers) is deliberately excluded: it would add gigabytes.
# On Linux the mic still needs the system PortAudio library (libportaudio2) at runtime.
# ruff: noqa
from importlib.util import find_spec

from PyInstaller.utils.hooks import collect_data_files, collect_submodules

# The extras are imported lazily inside functions, so PyInstaller can't see them on its own.
OPTIONAL = ["mss", "cv2", "sounddevice", "numpy", "paho.mqtt.client"]
EXCLUDES = [
    "torch",
    "torchvision",
    "transformers",
    "sentencepiece",
    "tokenizers",
    "safetensors",
    "tkinter",
    "matplotlib",
    "IPython",
    "pytest",
    "amqtt",
]

hiddenimports = collect_submodules("ifseen") + collect_submodules("rich")
hiddenimports += [m for m in OPTIONAL if find_spec(m.split(".")[0]) is not None]

a = Analysis(
    [f"{SPECPATH}/ifseen_entry.py"],
    pathex=[f"{SPECPATH}/../src"],
    # recipes/*.yaml, read through importlib.resources
    datas=collect_data_files("ifseen"),
    hiddenimports=hiddenimports,
    excludes=EXCLUDES,
    noarchive=False,
)
pyz = PYZ(a.pure)
exe = EXE(
    pyz,
    a.scripts,
    a.binaries,
    a.datas,
    [],
    name="ifseen",
    console=True,
    strip=False,
    # UPX breaks OpenCV/numpy shared libs on some platforms and trips antivirus heuristics.
    upx=False,
    runtime_tmpdir=None,
)
