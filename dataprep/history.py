"""処理履歴（JSON Lines）とエラーログ（ローテーションするログファイル）。"""

from __future__ import annotations

import json
import logging
import os
from logging.handlers import RotatingFileHandler
from pathlib import Path

LOGGER_NAME = "dataprep"


def default_home() -> Path:
    """履歴・ログの置き場所。環境変数 DATAPREP_HOME があればそこ、なければプロジェクトの data フォルダ。"""
    env = os.environ.get("DATAPREP_HOME")
    if env:
        return Path(env)
    return Path(__file__).resolve().parent.parent / "data"


def setup_logging(log_dir: Path | None = None, level: int = logging.INFO) -> logging.Logger:
    log_dir = Path(log_dir) if log_dir else default_home() / "logs"
    log_dir.mkdir(parents=True, exist_ok=True)
    logger = logging.getLogger(LOGGER_NAME)
    logger.setLevel(level)
    target = str((log_dir / "dataprep.log").resolve())
    if not any(isinstance(h, RotatingFileHandler) and h.baseFilename == target for h in logger.handlers):
        handler = RotatingFileHandler(target, maxBytes=1_000_000, backupCount=5, encoding="utf-8")
        handler.setFormatter(logging.Formatter("%(asctime)s [%(levelname)s] %(message)s"))
        logger.addHandler(handler)
    return logger


def get_logger() -> logging.Logger:
    return logging.getLogger(LOGGER_NAME)


class HistoryStore:
    """1回の処理を1行の JSON として追記する。壊れた行は読み飛ばす。"""

    def __init__(self, path: Path | None = None):
        self.path = Path(path) if path else default_home() / "history.jsonl"

    def append(self, record: dict) -> None:
        self.path.parent.mkdir(parents=True, exist_ok=True)
        with self.path.open("a", encoding="utf-8") as f:
            f.write(json.dumps(record, ensure_ascii=False, default=str) + "\n")

    def load(self, limit: int = 200) -> list[dict]:
        """新しい順に返す。"""
        if not self.path.is_file():
            return []
        records = []
        with self.path.open(encoding="utf-8", errors="replace") as f:
            for line in f:
                line = line.strip()
                if not line:
                    continue
                try:
                    item = json.loads(line)
                except json.JSONDecodeError:
                    continue
                if isinstance(item, dict):
                    records.append(item)
        return list(reversed(records))[:limit]
