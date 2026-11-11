"""Работа с KataGo в режиме анализа (JSON-протокол).

Один процесс KataGo обслуживает и бота, и разбор партий/задач. Всё считается
локально на компьютере, без запросов в интернет.
"""

from __future__ import annotations

import json
import os
import subprocess
import sys
import threading
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Callable, Optional

from ..board import BLACK, Game, to_gtp, from_gtp, Point

Callback = Callable[[dict], None]


def app_data_dir() -> Path:
    if sys.platform.startswith("win"):
        base = Path(os.environ.get("APPDATA", Path.home()))
    else:
        base = Path(os.environ.get("XDG_CONFIG_HOME", Path.home() / ".config"))
    d = base / "GoTrainer"
    d.mkdir(parents=True, exist_ok=True)
    return d


def project_root() -> Path:
    if getattr(sys, "frozen", False):  # собранный exe (PyInstaller)
        return Path(sys.executable).resolve().parent
    return Path(__file__).resolve().parents[2]


def katago_install_dir() -> Path:
    """Куда скачивать KataGo: папка katago рядом с игрой, а если туда нельзя писать
    (установка из .deb в /opt, AppImage, Program Files) — папка настроек пользователя."""
    d = project_root() / "katago"
    try:
        d.mkdir(parents=True, exist_ok=True)
        probe = d / ".write_test"
        probe.write_bytes(b"")
        probe.unlink()
        return d
    except OSError:
        return app_data_dir() / "katago"


def find_katago() -> tuple[Optional[Path], Optional[Path]]:
    """Ищет программу KataGo и файл нейросети в папке katago рядом с игрой."""
    exe_name = "katago.exe" if sys.platform.startswith("win") else "katago"
    for d in (project_root() / "katago", app_data_dir() / "katago"):
        exe = d / exe_name
        if exe.exists():
            models = sorted(list(d.glob("*.bin.gz")) + list(d.glob("*.txt.gz")), key=lambda p: p.stat().st_size)
            return exe, (models[-1] if models else None)
    return None, None


CONFIG_TEMPLATE = """# Сгенерировано игрой автоматически
logToStderr = false
logDir = {logdir}
reportAnalysisWinratesAs = BLACK
maxVisits = 500
numAnalysisThreads = 2
numSearchThreadsPerAnalysisThread = {threads}
nnMaxBatchSize = 32
nnCacheSizePowerOfTwo = 21
nnMutexPoolSizePowerOfTwo = 15
nnRandomize = true
"""


def write_config(threads: Optional[int] = None) -> Path:
    threads = threads or max(1, min(8, (os.cpu_count() or 2)))
    d = app_data_dir()
    logdir = (d / "katago_logs").as_posix()
    cfg = d / "analysis.cfg"
    cfg.write_text(CONFIG_TEMPLATE.format(threads=threads, logdir=logdir), encoding="utf-8")
    return cfg


@dataclass
class MoveInfo:
    move: str
    visits: int
    winrate: float  # для чёрных
    score_lead: float  # для чёрных
    prior: float
    pv: list[str]
    ownership: Optional[list[float]] = None

    @classmethod
    def from_json(cls, d: dict) -> "MoveInfo":
        return cls(d["move"], d.get("visits", 0), d.get("winrate", 0.5), d.get("scoreLead", 0.0),
                   d.get("prior", 0.0), d.get("pv", []), d.get("ownership"))


@dataclass
class Analysis:
    """Результат анализа одной позиции. Все оценки — с точки зрения чёрных."""
    turn: int
    winrate: float
    score_lead: float
    moves: list[MoveInfo]
    ownership: Optional[list[float]]
    policy: Optional[list[float]]
    size: int

    @classmethod
    def from_json(cls, d: dict, size: int) -> "Analysis":
        root = d.get("rootInfo", {})
        moves = [MoveInfo.from_json(m) for m in d.get("moveInfos", [])]
        return cls(d.get("turnNumber", 0), root.get("winrate", 0.5), root.get("scoreLead", 0.0),
                   moves, d.get("ownership"), d.get("policy"), size)

    @property
    def best(self) -> Optional[MoveInfo]:
        return self.moves[0] if self.moves else None

    def info_for(self, gtp_move: str) -> Optional[MoveInfo]:
        for m in self.moves:
            if m.move.upper() == gtp_move.upper():
                return m
        return None


class KataGo:
    def __init__(self, exe: Path, model: Path, config: Optional[Path] = None):
        self.exe = Path(exe)
        self.model = Path(model)
        self.config = config or write_config()
        self.proc: Optional[subprocess.Popen] = None
        self._callbacks: dict[str, tuple[Callback, int]] = {}
        self._lock = threading.Lock()
        self._counter = 0
        self._ready = threading.Event()
        self.error: Optional[str] = None
        self.stderr_tail: list[str] = []

    # --- запуск и остановка ---
    def start(self) -> None:
        kwargs: dict[str, Any] = {}
        if sys.platform.startswith("win"):
            kwargs["creationflags"] = 0x08000000  # CREATE_NO_WINDOW: без чёрного окна консоли
        env = dict(os.environ)
        env.setdefault("APPIMAGE_EXTRACT_AND_RUN", "1")  # сборка KataGo для Linux — это AppImage
        self.proc = subprocess.Popen(
            [str(self.exe), "analysis", "-config", str(self.config), "-model", str(self.model)],
            stdin=subprocess.PIPE, stdout=subprocess.PIPE, stderr=subprocess.PIPE,
            text=True, encoding="utf-8", bufsize=1, cwd=str(self.exe.parent), env=env, **kwargs)
        threading.Thread(target=self._read_stdout, daemon=True).start()
        threading.Thread(target=self._read_stderr, daemon=True).start()

    def wait_ready(self, timeout: float = 120) -> bool:
        return self._ready.wait(timeout)

    @property
    def alive(self) -> bool:
        return self.proc is not None and self.proc.poll() is None

    def stop(self) -> None:
        if self.proc and self.proc.poll() is None:
            try:
                self.proc.stdin.close()
                self.proc.terminate()
                self.proc.wait(3)
            except Exception:
                try:
                    self.proc.kill()
                except Exception:
                    pass
        self.proc = None

    def _read_stderr(self) -> None:
        assert self.proc
        for line in self.proc.stderr:
            line = line.rstrip()
            self.stderr_tail = (self.stderr_tail + [line])[-30:]
            if "Started, ready" in line:
                self._ready.set()
        if not self._ready.is_set():
            self.error = "\n".join(self.stderr_tail[-10:]) or "KataGo завершился при запуске"
            self._ready.set()

    def _read_stdout(self) -> None:
        assert self.proc
        for line in self.proc.stdout:
            line = line.strip()
            if not line.startswith("{"):
                continue
            try:
                data = json.loads(line)
            except json.JSONDecodeError:
                continue
            qid = data.get("id", "")
            with self._lock:
                entry = self._callbacks.get(qid)
                if entry is None:
                    continue
                cb, remaining = entry
                if "error" in data or data.get("isDuringSearch") is False or "noResults" in data:
                    remaining -= 1
                    if remaining <= 0:
                        del self._callbacks[qid]
                    else:
                        self._callbacks[qid] = (cb, remaining)
            try:
                cb(data)
            except Exception as e:  # ошибка в обработчике не должна ронять поток
                print("callback error:", e, file=sys.stderr)

    # --- запросы ---
    def query(self, payload: dict, callback: Callback, expected: int = 1) -> str:
        if not self.alive:
            raise RuntimeError("KataGo не запущен")
        with self._lock:
            self._counter += 1
            qid = f"q{self._counter}"
            self._callbacks[qid] = (callback, expected)
        payload = dict(payload, id=qid)
        self.proc.stdin.write(json.dumps(payload) + "\n")
        self.proc.stdin.flush()
        return qid

    def cancel(self, qid: str) -> None:
        if not self.alive:
            return
        with self._lock:
            self._callbacks.pop(qid, None)
        try:
            self.proc.stdin.write(json.dumps({"id": f"cancel-{qid}", "action": "terminate", "terminateId": qid}) + "\n")
            self.proc.stdin.flush()
        except Exception:
            pass

    @staticmethod
    def base_payload(game: Game, upto: Optional[int] = None) -> dict:
        p: dict[str, Any] = {
            "moves": game.gtp_moves(upto),
            "rules": "chinese" if game.rules == "chinese" else "japanese",
            "komi": game.komi,
            "boardXSize": game.size,
            "boardYSize": game.size,
        }
        init = game.initial_stones_gtp()
        if init:
            p["initialStones"] = init
        p["initialPlayer"] = "B" if game.first_to_play == BLACK else "W"
        return p

    def analyze_position(self, game: Game, callback: Callable[[Analysis], None], upto: Optional[int] = None,
                         visits: int = 200, ownership: bool = True, moves_ownership: bool = False,
                         policy: bool = False, allow_moves: Optional[list[str]] = None) -> str:
        n = len(game.moves) if upto is None else upto
        payload = self.base_payload(game, n)
        payload.update({"maxVisits": visits, "includeOwnership": ownership,
                        "includeMovesOwnership": moves_ownership, "includePolicy": policy})
        if allow_moves:
            player = "B" if (game.to_play if upto is None else _to_play_at(game, n)) == BLACK else "W"
            payload["allowMoves"] = [{"player": player, "moves": allow_moves, "untilDepth": 1}]

        def cb(d: dict) -> None:
            if "error" in d:
                callback(None)  # type: ignore[arg-type]
                return
            callback(Analysis.from_json(d, game.size))
        return self.query(payload, cb)

    def analyze_game(self, game: Game, on_turn: Callable[[Analysis], None], visits: int = 100,
                     turns: Optional[list[int]] = None) -> str:
        """Анализ всех позиций партии. on_turn вызывается для каждого хода по мере готовности."""
        turns = turns if turns is not None else list(range(len(game.moves) + 1))
        payload = self.base_payload(game, len(game.moves))
        payload.update({"maxVisits": visits, "includeOwnership": True, "analyzeTurns": turns})

        def cb(d: dict) -> None:
            if "error" in d or "noResults" in d:
                return
            on_turn(Analysis.from_json(d, game.size))
        return self.query(payload, cb, expected=len(turns))


def _to_play_at(game: Game, n: int) -> int:
    if n == 0:
        return game.first_to_play
    from ..board import other
    return other(game.moves[n - 1].color)


def gtp_to_point(move: str, size: int) -> Optional[Point]:
    return from_gtp(move, size)


def point_to_gtp(p: Optional[Point], size: int) -> str:
    return to_gtp(p, size)
