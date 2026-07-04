"""`openrtc logs --session` filters a JSONL log file by session_id (MAH-91)."""

from __future__ import annotations

from pathlib import Path

from typer.testing import CliRunner

from openrtc.cli import app

_LOG = "\n".join(
    [
        '{"session_id": "a", "level": "INFO", "message": "one"}',
        '{"session_id": "b", "level": "INFO", "message": "two"}',
        '{"session_id": "a", "level": "ERROR", "message": "three"}',
    ]
)


def test_logs_filters_by_session(tmp_path: Path) -> None:
    log_file = tmp_path / "worker.jsonl"
    log_file.write_text(_LOG, encoding="utf-8")

    result = CliRunner().invoke(app, ["logs", str(log_file), "--session", "a"])

    assert result.exit_code == 0, result.output
    assert "one" in result.output
    assert "three" in result.output
    assert "two" not in result.output


def test_logs_no_filter_prints_all(tmp_path: Path) -> None:
    log_file = tmp_path / "worker.jsonl"
    log_file.write_text(_LOG, encoding="utf-8")

    result = CliRunner().invoke(app, ["logs", str(log_file)])

    assert result.exit_code == 0, result.output
    for msg in ("one", "two", "three"):
        assert msg in result.output


def test_logs_missing_file_errors(tmp_path: Path) -> None:
    result = CliRunner().invoke(app, ["logs", str(tmp_path / "nope.jsonl")])

    assert result.exit_code != 0
