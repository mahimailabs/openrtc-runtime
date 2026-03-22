"""Sidecar metrics stream for workers (JSON Lines over a file or socket).

Each line is one JSON object (envelope) so a separate TUI or script can tail the
file. This is the contract for ``openrtc tui --watch``.

**Envelope (schema version 1)**

* ``schema_version`` (int): bump on breaking payload changes.
* ``kind`` (str): ``"snapshot"`` for full pool state; future kinds may add events.
* ``seq`` (int): monotonically increasing counter for this worker process.
* ``wall_time_unix`` (float): ``time.time()`` when the record was emitted.
* ``payload`` (dict): for ``kind == "snapshot"``, same shape as
  :meth:`PoolRuntimeSnapshot.to_dict`.
"""

from __future__ import annotations

import json
import time
from pathlib import Path
from threading import Lock
from typing import Any

from openrtc.resources import PoolRuntimeSnapshot

METRICS_STREAM_SCHEMA_VERSION = 1
KIND_SNAPSHOT = "snapshot"


def snapshot_envelope(*, seq: int, snapshot: PoolRuntimeSnapshot) -> dict[str, Any]:
    """Build a versioned JSON object for one line of the metrics stream."""
    return {
        "schema_version": METRICS_STREAM_SCHEMA_VERSION,
        "kind": KIND_SNAPSHOT,
        "seq": seq,
        "wall_time_unix": time.time(),
        "payload": snapshot.to_dict(),
    }


def parse_metrics_jsonl_line(line: str) -> dict[str, Any] | None:
    """Return a parsed snapshot record, or ``None`` if the line is not a snapshot."""
    stripped = line.strip()
    if not stripped:
        return None
    try:
        record: dict[str, Any] = json.loads(stripped)
    except json.JSONDecodeError:
        return None
    if record.get("schema_version") != METRICS_STREAM_SCHEMA_VERSION:
        return None
    if record.get("kind") != KIND_SNAPSHOT:
        return None
    return record


class JsonlMetricsSink:
    """Append-only JSONL writer; truncates the file when opened (new worker run)."""

    def __init__(self, path: Path) -> None:
        self._path = path
        self._file: Any = None
        self._seq = 0
        self._lock = Lock()

    def open(self) -> None:
        """Create parent dirs, truncate file, open for append."""
        self._path.parent.mkdir(parents=True, exist_ok=True)
        self._file = self._path.open("w", encoding="utf-8")

    def write_snapshot(self, snapshot: PoolRuntimeSnapshot) -> None:
        """Serialize one snapshot line and flush (thread-safe)."""
        with self._lock:
            if self._file is None:
                raise RuntimeError("JsonlMetricsSink.open() was not called")
            self._seq += 1
            record = snapshot_envelope(seq=self._seq, snapshot=snapshot)
            self._file.write(json.dumps(record, sort_keys=True) + "\n")
            self._file.flush()

    def close(self) -> None:
        with self._lock:
            if self._file is not None:
                self._file.close()
                self._file = None

    @property
    def seq(self) -> int:
        with self._lock:
            return self._seq
