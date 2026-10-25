"""Tests for the droid chirp synthesiser (no external audio dependencies)."""

from __future__ import annotations

import wave

from popelka import droid


def test_phrase_is_deterministic_and_bounded():
    a = droid.phrase(7)
    b = droid.phrase(7)
    assert a == b
    assert 0.15 < droid.duration(a) < 3.0
    assert max(abs(s) for s in a) <= 0.86


def test_different_seeds_differ():
    assert droid.phrase(1) != droid.phrase(2)


def test_write_wav_is_valid_pcm(tmp_path):
    samples = droid.phrase(3)
    path = droid.write_wav(tmp_path / "x" / "chirp.wav", samples)
    assert path.exists()
    with wave.open(str(path), "rb") as fh:
        assert fh.getnchannels() == 1
        assert fh.getsampwidth() == 2
        assert fh.getframerate() == droid.SAMPLE_RATE
        assert fh.getnframes() == len(samples)
