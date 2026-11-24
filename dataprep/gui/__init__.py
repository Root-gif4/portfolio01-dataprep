"""デスクトップ画面（Tkinter）。"""

from pathlib import Path


def launch(home: Path) -> None:
    from .app import launch as _launch
    _launch(home)
