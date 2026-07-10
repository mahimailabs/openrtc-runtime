# Rust inference offload via PyO3: scoped spike and decision

Status: **design / research (Loop 1)**. Not implemented. The spike code lives in `spikes/pyo3-vad/`.

## Question

FlowCat proved a Rust reimplementation of a Pipecat-style runtime wins big on density (flat p99 to 2,000 calls vs Pipecat collapsing by 1,000). Can OpenRTC borrow that selectively: keep the Python API and DX, write the hot path in Rust via PyO3, and call it from Python? Specifically, is a Rust Silero-VAD kernel (releasing the GIL) worth building, pipecat backend first?

## What the spike proves (mechanism: viable, cheap)

`spikes/pyo3-vad/` is a minimal PyO3 module built with `maturin` (rustc 1.95, pyo3 0.24). It runs identical CPU-bound work three ways and measures parallel speedup across 8 Python threads:

```
python (GIL-held)      parallel-speedup=1.00x   fully serialized by the GIL
rust (holds GIL)       parallel-speedup=0.96x   also serialized (proves it is the GIL, not the language)
rust (releases GIL)    parallel-speedup=4.43x   py.allow_threads -> real cross-core parallelism
```

Conclusions from the spike:
- **PyO3 + `py.allow_threads` genuinely releases the GIL.** Rust CPU work parallelizes ~4.4x on 8 threads where pure Python serializes at 1.0x. The Python-DX / Rust-core hybrid works exactly as hoped.
- **It is cheap to stand up.** 7-second release build, one small crate, `maturin develop` into a venv. The "can we even PyO3?" risk is retired.

So the *mechanism* is a clear yes and belongs in the toolbox. The harder question is whether **VAD specifically** is the right thing to offload.

## The counter-evidence (why a VAD-only kernel is low-leverage)

Three findings say offloading Silero VAD alone would not move density much:

1. **onnxruntime already releases the GIL during `Run()`.** Pipecat's `SileroVADAnalyzer` calls onnxruntime, whose Python binding drops the GIL for the C++ inference. So the VAD *compute* already parallelizes across threads in pure Python. A Rust wrapper around the same ONNX model would not add GIL headroom to the part that is already GIL-free.

2. **FlowCat's own benchmark says the bottleneck is frame routing, not inference.** From `../../study/flowcat/bench/RESULTS.md`, the pipecat framework floor is:
   - **~105 µs/frame** routing (~15 µs x 7 processor hops), **GIL-bound**.
   - **~94 concurrent calls/process** ceiling on frame routing alone (real I/O drops it to tens).
   - A ~100 to 160 ms GC/GIL max-latency floor even at 10 calls.
   FlowCat's win comes from rewriting the **whole per-frame media loop** in Rust, not from a faster VAD. The Python cost that pins a core is the aggregate frame orchestration at ~50 fps x N sessions, which VAD offload does not touch.

3. **The livekit backend already sidesteps this without any Rust**, by running VAD and turn detection in a **separate inference process** (the `inference: true` executor). That is why OpenRTC-on-livekit holds ~1 to 2 ms p99 to 100 sessions today. The proven, shipping answer to "keep inference off the session loop" is process isolation, not a Rust module.

Put together: a Rust VAD kernel would parallelize work that onnxruntime already parallelizes, while leaving the actual GIL ceiling (frame routing) untouched, and duplicating a job process isolation already does on livekit.

## Decision

**Do not build a Rust VAD kernel now. Keep PyO3 as a de-risked, deferred option for the frame-routing loop only, and reach for non-Rust levers first.**

- **Mechanism: keep.** The spike proves PyO3/allow_threads works and is cheap. Retain it in the toolbox for the one place it would actually pay off.
- **VAD-only Rust kernel: reject.** Low leverage (onnxruntime already GIL-frees the compute; the bottleneck is elsewhere; livekit already process-offloads).
- **The real Rust target, if ever pursued, is the frame-routing/scheduler hot loop.** That is a large surface (essentially FlowCat's whole runtime). If Python density past its ceiling becomes a hard requirement for a pipecat backend, the higher-expected-value move is to **evaluate adopting or partnering with FlowCat** (a Pipecat-API-compatible Rust runtime that already did this) rather than growing a bespoke PyO3 frame loop inside OpenRTC.
- **Non-Rust first moves (cover most of the need):**
  1. **Shared prewarm** (see `framework-agnostic-backend.md`): load one Silero VAD + turn model per worker and share it across sessions. This removes the per-session model-load and memory tax that Pipecat pays today, with zero Rust.
  2. **Separate inference process for the pipecat backend**, mirroring livekit's inference executor, so per-frame ONNX stays off the session event loop at density.
  Only if these two are measured and still insufficient does the frame-loop-in-Rust question reopen.

## Open questions

- **Where exactly is the pipecat GIL ceiling for OpenRTC's target load?** FlowCat measured ~94 calls/process on frame routing. OpenRTC's density goal is 50+/worker. If 50 to 100/worker is the target, pipecat-in-Python plus shared prewarm plus a separate inference process may already clear it, making Rust unnecessary. This needs a real measurement against an OpenRTC pipecat backend once it exists.
- **Distribution cost of ever shipping Rust.** A Rust module means per-platform wheels (`maturin`, abi3), a Rust CI toolchain, and a heavier release. That cost is only justified by a proven, large density win, which VAD offload is not.
- **uvloop.** FlowCat's laptop numbers used uvloop. Does OpenRTC's pipecat backend adopt uvloop by default (a free Python-side win before any Rust)?

## Task list for implementation (Loop 2)

1. **No Rust in Loop 2.** Do not build the VAD kernel.
2. In the pipecat backend work (`framework-agnostic-backend.md`), implement **shared prewarm** and a **separate inference process** option; measure calls/worker at target load.
3. Keep `spikes/pyo3-vad/` as the reference artifact. Only revisit Rust if step 2's measurement shows Python plus shared prewarm plus process isolation cannot hit the density target, and then scope it to the frame loop (or evaluate FlowCat) rather than VAD.
