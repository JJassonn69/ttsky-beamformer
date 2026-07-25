from __future__ import annotations

import importlib.util
from pathlib import Path

import numpy as np


ROOT = Path(__file__).resolve().parents[2]


def load_tool(name: str, filename: str):
    path = ROOT / "v3/tools" / filename
    spec = importlib.util.spec_from_file_location(name, path)
    assert spec is not None and spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def test_switched_noise_deck_limits_saved_vectors_and_records_scaling() -> None:
    tool = load_tool("switched_noise_test", "run_vacask_switched_noise.py")
    deck = tool.switched_deck(
        8,
        "",
        stop_us=20.0,
        step_ns=0.25,
        mode="zoh",
        seed=104729,
        noise_fmin_hz=10e3,
        noise_fmax_hz=64e6,
        oversample=2,
        noise_scale=0.01,
        noise_debug=0,
        precondition_us=20.0,
    )
    assert "save v(outp_pad) v(outn_pad)" in deck
    assert "save outp_pad outn_pad" not in deck
    assert "save default" not in deck
    assert 'store="noise_ic" write=0' in deck
    assert 'ic="noise_ic" icmode="uic"' in deck
    assert "noisescale=0.01" in deck


def test_two_pole_receiver_preserves_dc() -> None:
    tool = load_tool("switched_noise_filter_test", "run_vacask_switched_noise.py")
    time_s = np.linspace(0.0, 2e-6, 8001)
    value = np.full_like(time_s, 0.125)
    filtered = tool.two_pole_receiver(time_s, value)
    np.testing.assert_allclose(filtered, value, rtol=0.0, atol=1e-15)


def test_resume_requires_waveform_to_reach_requested_stop() -> None:
    tool = load_tool("switched_noise_resume_test", "run_vacask_switched_noise.py")
    complete = {"time": np.asarray([0.0, 110e-6])}
    truncated = {"time": np.asarray([0.0, 109e-6])}
    nonfinite = {"time": np.asarray([0.0, np.nan])}
    assert tool.waveform_reaches_stop(complete, 110.0)
    assert not tool.waveform_reaches_stop(truncated, 110.0)
    assert not tool.waveform_reaches_stop(nonfinite, 110.0)


def test_finite_edge_commutator_is_zero_mean_and_energy_is_closed() -> None:
    tool = load_tool("noise_folding_test", "run_noise_folding_crosscheck.py")
    coefficients, coefficient_energy, waveform_energy = tool.commutator_coefficients(
        4e6, 5e-9, 16
    )
    assert abs(coefficients[0]) <= 1e-12
    assert abs(coefficient_energy - waveform_energy) / waveform_energy <= 0.01
    assert abs(coefficients[1]) > abs(coefficients[3]) > abs(coefficients[5])
