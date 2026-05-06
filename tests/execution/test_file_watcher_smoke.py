"""End-to-end smoke test for the file watcher (MAH-80, Step 9).

Exercises the full pipeline — ``watchfiles.awatch`` -> ``_handle_change_batch``
-> trailing debounce flush -> ``on_change`` callback — against a real
file on disk. The unit tests in ``test_file_watcher.py`` cover each
seam in isolation; this test confirms the seams stay glued together
when wired through the live filesystem watcher.
"""

from __future__ import annotations

import asyncio
import time
from pathlib import Path

import pytest

from openrtc import FileChange, FileWatcher


@pytest.mark.asyncio
async def test_filewatcher_smoke_against_real_tempdir(tmp_path: Path) -> None:
    target = tmp_path / "agent.py"
    target.write_text("# initial contents\n")

    received: list[list[FileChange]] = []

    async def record_changes(changes: list[FileChange]) -> None:
        received.append(list(changes))

    watcher = FileWatcher(record_changes, debounce_ms=200, paths=[target])
    await watcher.start()
    try:
        # Give watchfiles a moment to install the OS-level watch.
        await asyncio.sleep(0.15)

        # One real edit on disk.
        target.write_text("# modified contents\n")

        # Wait long enough for the watchfiles batch + 200ms debounce + dispatch.
        deadline = time.monotonic() + 3.0
        while time.monotonic() < deadline and not received:
            await asyncio.sleep(0.05)

        assert received, (
            f"on_change never fired within 3s; tempdir={tmp_path}, "
            f"watcher.state={watcher.state}"
        )
        # Exactly one callback for one logical edit.
        assert len(received) == 1, (
            f"expected exactly one callback, got {len(received)}: {received!r}"
        )
        # The callback receives a list of FileChange touching our file.
        paths = {fc.path.resolve() for fc in received[0]}
        assert target.resolve() in paths
        change_types = {fc.change_type for fc in received[0]}
        # Editor-style writes can land as modified or created depending on
        # the platform and write strategy; both are valid ends of the contract.
        assert change_types <= {"created", "modified", "deleted"}
        assert "deleted" not in change_types
    finally:
        await watcher.stop()
        assert watcher.state == "stopped"
        # Clean shutdown: no leaked watch task or flush task.
        assert watcher._watch_task is None  # noqa: SLF001
        assert watcher._flush_task is None  # noqa: SLF001
