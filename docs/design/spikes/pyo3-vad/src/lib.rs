// Minimal PyO3 spike: prove that CPU-bound work in Rust can run OFF the GIL,
// so N concurrent Python threads (one per voice session) parallelize instead
// of serializing. This is the mechanism a Rust inference/frame kernel would use.
// The `busy` loop stands in for a per-frame inference kernel; a real Silero port
// swaps it for an `ort::Session::run` call (which does the same allow_threads dance).

use pyo3::prelude::*;

fn busy(iters: u64) -> f64 {
    let mut acc = 0.0f64;
    for i in 0..iters {
        acc += (i as f64).sqrt().sin();
    }
    acc
}

/// CPU-bound work that RELEASES the GIL for its duration (the Rust-offload path).
#[pyfunction]
fn cpu_work_release_gil(py: Python<'_>, iters: u64) -> f64 {
    py.allow_threads(|| busy(iters))
}

/// Same work, but HOLDS the GIL the whole time (what pure-Python inline code does).
#[pyfunction]
fn cpu_work_hold_gil(_py: Python<'_>, iters: u64) -> f64 {
    busy(iters)
}

#[pymodule]
fn pyo3_vad_spike(m: &Bound<'_, PyModule>) -> PyResult<()> {
    m.add_function(wrap_pyfunction!(cpu_work_release_gil, m)?)?;
    m.add_function(wrap_pyfunction!(cpu_work_hold_gil, m)?)?;
    Ok(())
}
