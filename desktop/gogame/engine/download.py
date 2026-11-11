"""Скачивание KataGo и нейросети (один раз, ~120 МБ). Дальше всё работает без интернета."""

from __future__ import annotations

import os
import shutil
import stat
import sys
import tempfile
import urllib.request
import zipfile
from pathlib import Path
from typing import Callable, Optional

KATAGO_VERSION = "v1.16.4"
RELEASE = f"https://github.com/lightvector/KataGo/releases/download/{KATAGO_VERSION}"

VARIANTS = {
    "cpu": "Процессор (CPU, AVX2) — работает везде, медленнее",
    "gpu": "Видеокарта (OpenCL) — намного быстрее, нужна видеокарта с драйверами",
    "cpu-old": "Процессор без AVX2 (очень старые компьютеры)",
}

# Нейросеть g170e b20 официально выложена в релизах KataGo на GitHub.
# Более новые и сильные сети можно скачать вручную с https://katagotraining.org/networks/
# и положить файл *.bin.gz в папку katago — игра возьмёт самый большой файл.
MODEL_URL = ("https://github.com/lightvector/KataGo/releases/download/v1.4.5/"
             "g170e-b20c256x2-s5303129600-d1228401921.bin.gz")


def engine_url(variant: str) -> str:
    plat = "windows-x64" if sys.platform.startswith("win") else "linux-x64"
    kind = {"cpu": "eigenavx2", "gpu": "opencl", "cpu-old": "eigen"}[variant]
    return f"{RELEASE}/katago-{KATAGO_VERSION}-{kind}-{plat}.zip"


Progress = Callable[[str, int, int], None]  # (что качаем, скачано байт, всего байт)


def _download(url: str, dest: Path, what: str, progress: Optional[Progress]) -> None:
    req = urllib.request.Request(url, headers={"User-Agent": "GoTrainer"})
    with urllib.request.urlopen(req, timeout=60) as r:
        total = int(r.headers.get("Content-Length") or 0)
        done = 0
        with open(dest, "wb") as f:
            while True:
                chunk = r.read(1 << 16)
                if not chunk:
                    break
                f.write(chunk)
                done += len(chunk)
                if progress:
                    progress(what, done, total)


def install(target_dir: Path, variant: str = "cpu", progress: Optional[Progress] = None) -> tuple[Path, Path]:
    """Скачивает KataGo и сеть в target_dir. Возвращает (путь к программе, путь к сети)."""
    target_dir.mkdir(parents=True, exist_ok=True)
    exe_name = "katago.exe" if sys.platform.startswith("win") else "katago"
    with tempfile.TemporaryDirectory() as tmp:
        zpath = Path(tmp) / "katago.zip"
        _download(engine_url(variant), zpath, "программа KataGo", progress)
        with zipfile.ZipFile(zpath) as z:
            for member in z.infolist():
                name = Path(member.filename).name
                if not name or member.is_dir():
                    continue
                with z.open(member) as src, open(target_dir / name, "wb") as dst:
                    shutil.copyfileobj(src, dst)
    exe = target_dir / exe_name
    if not sys.platform.startswith("win"):
        exe.chmod(exe.stat().st_mode | stat.S_IXUSR | stat.S_IXGRP | stat.S_IXOTH)
    model = target_dir / MODEL_URL.rsplit("/", 1)[1]
    if not model.exists():
        part = model.with_suffix(".part")
        _download(MODEL_URL, part, "нейросеть", progress)
        os.replace(part, model)
    return exe, model


if __name__ == "__main__":
    import argparse

    ap = argparse.ArgumentParser(description="Скачать KataGo для игры")
    ap.add_argument("--variant", choices=list(VARIANTS), default="cpu")
    ap.add_argument("--dir", default=str(Path(__file__).resolve().parents[2] / "katago"))
    args = ap.parse_args()

    def show(what, done, total):
        if total:
            print(f"\r{what}: {done * 100 // total}%", end="", flush=True)

    exe, model = install(Path(args.dir), args.variant, show)
    print(f"\nГотово: {exe}\n{model}")
