# PyO3 GIL-release spike

Throwaway spike for `../rust-inference-offload.md`. It proves the mechanism a Rust
inference/frame kernel would rely on: CPU-bound work in Rust wrapped in
`py.allow_threads(...)` releases the GIL, so N Python threads (one per voice
session) run in parallel instead of serializing. `busy()` stands in for a per-frame
kernel; a real Silero port swaps it for an `ort::Session::run` call.

Not built by CI, not part of the package. Reproduce:

```bash
cd docs/design/spikes/pyo3-vad
uv venv --python 3.13 && uv pip install maturin
.venv/bin/maturin develop --release
.venv/bin/python bench.py
```

## Measured (Apple M-series, 10 cores, 8 threads, release build)

```
python (GIL-held)      single=  73ms  8x-threads= 584ms  parallel-speedup=1.00x
rust (holds GIL)       single= 133ms  8x-threads=1111ms  parallel-speedup=0.96x
rust (releases GIL)    single= 133ms  8x-threads= 240ms  parallel-speedup=4.43x
```

Reading: pure-Python CPU work serializes at 1.00x under threads; Rust that holds the
GIL also serializes (0.96x, proving it is the GIL not the language); Rust that
releases the GIL parallelizes (4.43x on 8 threads). Toolchain build was 7s.
