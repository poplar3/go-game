"""Запуск KataGo в фоне и доставка результатов в поток интерфейса."""

from __future__ import annotations

import threading
from pathlib import Path
from typing import Callable, Optional

from PySide6.QtCore import QObject, QSettings, Signal

from ..engine.katago import KataGo, find_katago, write_config


class EngineManager(QObject):
    status_changed = Signal(str)
    ready_changed = Signal(bool)
    _deliver = Signal(object, object)

    def __init__(self, parent=None):
        super().__init__(parent)
        self.engine: Optional[KataGo] = None
        self.ready = False
        self.status = "ИИ не запущен"
        self._deliver.connect(self._on_deliver)

    def _on_deliver(self, cb, data):
        cb(data)

    def _set_status(self, text: str, ready: bool) -> None:
        self.status = text
        self.ready = ready
        self.status_changed.emit(text)
        self.ready_changed.emit(ready)

    def paths(self) -> tuple[Optional[Path], Optional[Path]]:
        s = QSettings()
        exe = s.value("katago/exe", "")
        model = s.value("katago/model", "")
        auto_exe, auto_model = find_katago()
        exe_p = Path(exe) if exe and Path(exe).exists() else auto_exe
        model_p = Path(model) if model and Path(model).exists() else auto_model
        return exe_p, model_p

    def start(self) -> None:
        self.stop()
        exe, model = self.paths()
        if not exe or not model:
            self._set_status("ИИ KataGo не найден — играет встроенный бот. Установите KataGo в настройках.", False)
            return
        threads = int(QSettings().value("katago/threads", 0) or 0) or None
        cfg = write_config(threads)
        self._set_status("Запускаю ИИ KataGo…", False)
        engine = KataGo(exe, model, cfg)

        def run():
            try:
                engine.start()
                ok = engine.wait_ready(180)
            except Exception as e:  # нет прав, неверный файл и т. п.
                engine.error = str(e)
                ok = False
            if ok and engine.error is None and engine.alive:
                self.engine = engine
                self._deliver.emit(lambda _: self._set_status(f"ИИ KataGo готов ({model.name})", True), None)
            else:
                err = engine.error or "неизвестная ошибка"
                engine.stop()
                self._deliver.emit(lambda _: self._set_status(f"Не удалось запустить KataGo: {err}", False), None)

        threading.Thread(target=run, daemon=True).start()

    def stop(self) -> None:
        if self.engine:
            self.engine.stop()
        self.engine = None
        self.ready = False

    def available(self) -> bool:
        return self.ready and self.engine is not None and self.engine.alive

    def in_ui(self, cb: Callable) -> Callable:
        """Оборачивает обработчик, чтобы он вызывался в главном потоке."""
        def wrapper(data):
            self._deliver.emit(cb, data)
        return wrapper
