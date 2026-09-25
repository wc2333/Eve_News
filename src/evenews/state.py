"""Remember what was already published so the digest does not repeat itself."""

from __future__ import annotations

import json
from datetime import date, timedelta
from pathlib import Path


class StateStore:
    def __init__(self, path: Path) -> None:
        self.path = Path(path)
        self.data: dict = {"seen": {}, "runs": []}
        if self.path.is_file():
            try:
                loaded = json.loads(self.path.read_text(encoding="utf-8"))
            except (OSError, ValueError):
                loaded = None
            if isinstance(loaded, dict):
                self.data.update(loaded)
        self.data.setdefault("seen", {})
        self.data.setdefault("runs", [])

    def seen_before(self, item_fp: str, not_before: str, run_date: str = "") -> bool:
        """True when the item was already published on an *earlier day*.

        Entries marked by a run of the same day must not disqualify a rerun,
        otherwise re-running ``evenews run`` after fixing a source would leave
        every section empty.
        """
        first_seen = str(self.data["seen"].get(item_fp) or "")
        if not first_seen or first_seen < not_before:
            return False
        return not run_date or first_seen < run_date

    def mark_seen(self, fingerprints: list[str], run_date: str) -> None:
        for fp in fingerprints:
            self.data["seen"].setdefault(fp, run_date)

    def prune(self, run_date: str, keep_days: int) -> None:
        cutoff = (date.fromisoformat(run_date) - timedelta(days=keep_days)).isoformat()
        self.data["seen"] = {fp: d for fp, d in self.data["seen"].items() if str(d) >= cutoff}

    def record_run(self, entry: dict) -> None:
        runs = [r for r in self.data["runs"] if r.get("run_date") != entry.get("run_date")]
        runs.append(entry)
        self.data["runs"] = runs[-120:]

    def save(self) -> None:
        self.path.parent.mkdir(parents=True, exist_ok=True)
        text = json.dumps(self.data, ensure_ascii=False, indent=2)
        self.path.write_text(text + "\n", encoding="utf-8")
