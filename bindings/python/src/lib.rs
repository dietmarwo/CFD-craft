//! Thin JSON bridge to the same preflight and solver used by the native CLI.
use cfd_craft::{
    case::{Case, hash_bytes},
    input,
    solver::{Control, Summary},
};
use pyo3::{
    create_exception,
    exceptions::{PyRuntimeError, PyValueError},
    prelude::*,
};
use std::{
    path::PathBuf,
    sync::{Arc, atomic::Ordering, mpsc},
    time::Duration,
};

create_exception!(
    _native,
    NativeError,
    PyValueError,
    "Rejected case or failed execution."
);

fn source_sha256() -> String {
    hash_bytes(
        format!(
            "core:{};python:{}",
            cfd_craft::SOURCE_SHA256,
            env!("CFD_SOURCE_SHA")
        )
        .as_bytes(),
    )
}

#[pyfunction]
fn describe_json() -> String {
    serde_json::json!({
        "name": "CFD-craft", "version": env!("CARGO_PKG_VERSION"), "interface": "python",
        "source_sha256": source_sha256(), "compiler": cfd_craft::RUSTC_VERSION,
        "case_schema": schemars::schema_for!(Case), "result_schema": schemars::schema_for!(Summary),
        "experimental_validation": "not_validated",
        "capabilities": ["check", "simulate_summary", "cancel_file", "python_signals"],
        "archive_interface": "native cfd-craft CLI (cargo install cfd-craft-cli)"
    })
    .to_string()
}

#[pyfunction]
fn check_json(py: Python<'_>, case: Vec<u8>) -> String {
    py.detach(move || {
        let report = match input::parse_case(&case) {
            Ok(case) => input::full_check(&case).0,
            Err(report) => report,
        };
        serde_json::to_string(&report).expect("check report")
    })
}

#[pyfunction]
#[pyo3(signature = (case, cancel_file=None))]
fn simulate_json(py: Python<'_>, case: Vec<u8>, cancel_file: Option<String>) -> PyResult<String> {
    // Validate bounded wall time before constructing Duration; also refuse host
    // memory exactly as the native CLI does, before allocating solver fields.
    let case = py
        .detach(move || {
            let case = input::parse_case(&case).map_err(|r| serde_json::to_string(&r).unwrap())?;
            let (mut report, _) = input::full_check(&case);
            input::refuse_host_memory(&mut report);
            if !report.valid {
                return Err(serde_json::to_string(&report).unwrap());
            }
            Ok(case)
        })
        .map_err(NativeError::new_err)?;
    let cancel = cancel_file.map(PathBuf::from);
    let control = Arc::new(Control::with_poll(case.run.wall_time_limit_s, move || {
        if cancel.as_ref().is_some_and(|p| p.exists()) {
            Err("cancelled".into())
        } else {
            Ok(())
        }
    }));
    let shared = Arc::clone(&control);
    let (sender, mut receiver) = mpsc::channel();
    let worker = std::thread::Builder::new()
        .name("cfd-craft".into())
        .spawn(move || {
            let run = || -> Result<String, String> {
                let pool = rayon::ThreadPoolBuilder::new()
                    .num_threads(case.run.threads)
                    .build()
                    .map_err(|e| e.to_string())?;
                let mut result = pool.install(|| cfd_craft::solver::run(&case, &shared, None))?;
                result.summary.source_sha256 = source_sha256();
                serde_json::to_string(&result.summary).map_err(|e| e.to_string())
            };
            let _ = sender.send(run());
        })
        .map_err(|e| PyRuntimeError::new_err(e.to_string()))?;
    let mut signal = None;
    let value = loop {
        let (back, received) = py.detach(move || {
            let value = receiver.recv_timeout(Duration::from_millis(50));
            (receiver, value)
        });
        receiver = back;
        match received {
            Ok(value) => break Some(value),
            Err(mpsc::RecvTimeoutError::Disconnected) => break None,
            Err(mpsc::RecvTimeoutError::Timeout) => {
                if signal.is_none()
                    && let Err(error) = py.check_signals()
                {
                    control.cancelled.store(true, Ordering::Relaxed);
                    signal = Some(error);
                }
            }
        }
    };
    let joined = py.detach(move || worker.join());
    if let Some(error) = signal {
        return Err(error);
    }
    match (value, joined) {
        (Some(value), Ok(())) => value.map_err(NativeError::new_err),
        _ => Err(PyRuntimeError::new_err("CFD-craft worker thread panicked")),
    }
}

#[pymodule]
fn _native(module: &Bound<'_, PyModule>) -> PyResult<()> {
    module.add("__version__", env!("CARGO_PKG_VERSION"))?;
    module.add("NativeError", module.py().get_type::<NativeError>())?;
    module.add_function(wrap_pyfunction!(describe_json, module)?)?;
    module.add_function(wrap_pyfunction!(check_json, module)?)?;
    module.add_function(wrap_pyfunction!(simulate_json, module)?)?;
    Ok(())
}
