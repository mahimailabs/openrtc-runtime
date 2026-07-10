"""The neutral-core guarantee: ``import openrtc`` pulls no voice framework.

Mirrors voicegateway's check. The framework (livekit today, pipecat next) is
imported lazily only when a backend is selected, so the package top level stays
framework-free. Run in a subprocess to observe a clean ``sys.modules``.
"""

from __future__ import annotations

import subprocess
import sys


def test_importing_openrtc_does_not_import_livekit() -> None:
    code = (
        "import sys, openrtc\n"
        "leaked = sorted(m for m in sys.modules if m.split('.')[0] == 'livekit')\n"
        "assert not leaked, leaked\n"
        "assert hasattr(openrtc, 'AgentPool')\n"
    )
    result = subprocess.run(
        [sys.executable, "-c", code],
        capture_output=True,
        text=True,
        check=False,
    )
    assert result.returncode == 0, (
        f"import openrtc leaked a framework:\n{result.stdout}\n{result.stderr}"
    )
