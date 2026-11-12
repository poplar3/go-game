# -*- mode: python -*-
# Сборка самостоятельной программы GoTrainer (Windows и Linux):
#     pyinstaller --noconfirm packaging/gotrainer.spec
# Результат: dist/GoTrainer/ (GoTrainer.exe или GoTrainer).
import sys
from pathlib import Path

ROOT = Path(SPECPATH).parent  # noqa: F821 (SPECPATH задаёт PyInstaller)
PKG = ROOT / "gogame"

a = Analysis(  # noqa: F821
    [str(ROOT / "start.py")],
    pathex=[str(ROOT)],
    datas=[
        (str(PKG / "problems" / "problems.json"), "gogame/problems"),
        (str(PKG / "problems" / "library.json.gz"), "gogame/problems"),
        (str(PKG / "icon.png"), "gogame"),
    ],
    excludes=["tkinter"],
    noarchive=False,
)
pyz = PYZ(a.pure)  # noqa: F821
exe = EXE(  # noqa: F821
    pyz,
    a.scripts,
    [],
    exclude_binaries=True,
    name="GoTrainer",
    console=False,
    icon=str(ROOT / "packaging" / "icon.ico") if sys.platform.startswith("win") else None,
)
coll = COLLECT(exe, a.binaries, a.datas, name="GoTrainer")  # noqa: F821
