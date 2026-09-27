"""BENCH_FFI_ROUTE=1: deliver audio and video stream events only to the stream they belong to.

A prototype of the upstream fix for livekit.rtc's FfiQueue, which offers every FFI event to every
subscriber in the process. Only AudioStream and VideoStream consume stream events, and each
checks the stream handle itself, so routing those events by ``stream_handle`` changes no
behaviour; every other event type is broadcast as before.
"""

import weakref
from typing import Any

from livekit.rtc import AudioStream, VideoStream
from livekit.rtc._ffi_client import FfiQueue

_STREAM_EVENTS = ("audio_stream_event", "video_stream_event")
# queue id -> the stream that owns it
_owner: dict[int, "weakref.ref[Any]"] = {}
_orig_put = FfiQueue.put
_orig_unsubscribe = FfiQueue.unsubscribe


def _put(self: FfiQueue, item: Any) -> None:  # type: ignore[type-arg]
    which = item.WhichOneof("message")
    if which not in _STREAM_EVENTS:
        _orig_put(self, item)
        return
    handle = getattr(item, which).stream_handle
    with self._lock:
        for queue, loop, _ in self._subscribers:
            ref = _owner.get(id(queue))
            stream = ref() if ref else None
            if stream is not None and stream._ffi_handle.handle == handle:
                loop.call_soon_threadsafe(queue.put_nowait, item)
                return


def _unsubscribe(self: FfiQueue, queue: Any) -> None:  # type: ignore[type-arg]
    _owner.pop(id(queue), None)
    _orig_unsubscribe(self, queue)


def _register(cls: type) -> None:
    orig_init = cls.__init__

    def __init__(self: Any, *args: Any, **kwargs: Any) -> None:
        orig_init(self, *args, **kwargs)
        _owner[id(self._ffi_queue)] = weakref.ref(self)

    cls.__init__ = __init__


def install() -> None:
    _register(AudioStream)
    _register(VideoStream)
    FfiQueue.put = _put  # type: ignore[method-assign]
    FfiQueue.unsubscribe = _unsubscribe  # type: ignore[method-assign]
