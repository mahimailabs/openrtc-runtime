"""Hot reload subsystem (coroutine mode): re-import edited agent modules and
re-bind live sessions at a turn boundary without dropping calls.

The family follows the project convention: ``base_reload.py`` holds the shared
protocols and result types, variant siblings implement one concern each
(``module_reloader``, ``session_registry``, ``rebind``, ``pin``, ``reporter``),
and ``coordinator`` wires them to the :class:`~openrtc.runtime.file_watcher.FileWatcher`.
"""

from __future__ import annotations
