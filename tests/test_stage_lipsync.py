"""口型驱动的测试：不碰声卡、不碰窗口，直接喂合成波形。"""

from __future__ import annotations

from array import array

import pytest

from stage.lipsync import (
    MouthDriver,
    compute_envelope,
    envelope_duration_ms,
    mouth_value,
)


def pcm(*values: int) -> bytes:
    """把一串 16 位采样打成 bytes。"""
    return array("h", values).tobytes()


def constant(amplitude: int, count: int) -> list[int]:
    return [amplitude] * count


def test_loud_then_silent_becomes_one_and_zero() -> None:
    """采样率 1000、窗口 50ms、单声道：每窗 50 个采样。"""
    data = pcm(*constant(10_000, 50), *constant(0, 50))

    envelope = compute_envelope(data, sample_rate=1000, channels=1, frame_ms=50)

    assert envelope == (1.0, 0.0)


def test_quiet_frames_still_open_the_mouth() -> None:
    """轻声也要张得开：按这段音频自己的峰值归一，而不是按满量程。"""
    data = pcm(*constant(2000, 50), *constant(4000, 50))

    envelope = compute_envelope(data, sample_rate=1000, channels=1, frame_ms=50)

    assert envelope[0] == pytest.approx(0.5**0.5)
    assert envelope[1] == 1.0


def test_pure_silence_keeps_the_frame_count() -> None:
    """全静音返回等长的 0，而不是空元组：长度是"这段有多长"的信息。"""
    envelope = compute_envelope(pcm(*constant(0, 100)), sample_rate=1000, channels=1, frame_ms=50)

    assert envelope == (0.0, 0.0)


def test_stereo_counts_both_channels_in_one_frame() -> None:
    data = pcm(*constant(1000, 100))

    envelope = compute_envelope(data, sample_rate=1000, channels=2, frame_ms=50)

    assert len(envelope) == 1


def test_odd_byte_count_is_trimmed_instead_of_raising() -> None:
    envelope = compute_envelope(
        pcm(1000, 1000) + b"\x01", sample_rate=1000, channels=1, frame_ms=50
    )

    assert envelope == (1.0,)


@pytest.mark.parametrize(
    ("sample_rate", "channels", "frame_ms"),
    [(0, 1, 50), (-1, 1, 50), (1000, 0, 50), (1000, 1, 0)],
)
def test_invalid_parameters_return_an_empty_envelope(
    sample_rate: int, channels: int, frame_ms: int
) -> None:
    envelope = compute_envelope(
        b"\x00\x00", sample_rate=sample_rate, channels=channels, frame_ms=frame_ms
    )

    assert envelope == ()


def test_empty_buffer_returns_an_empty_envelope() -> None:
    assert compute_envelope(b"", sample_rate=1000, channels=1) == ()
    assert compute_envelope(b"\x01", sample_rate=1000, channels=1) == ()


def test_envelope_duration() -> None:
    assert envelope_duration_ms((0.0, 0.5, 1.0), frame_ms=50) == 150.0
    assert envelope_duration_ms((), frame_ms=50) == 0.0


def test_mouth_value_follows_elapsed_time() -> None:
    envelope = (0.0, 0.5, 1.0)

    assert mouth_value(envelope, 0.0, frame_ms=50) == 0.0
    assert mouth_value(envelope, 60.0, frame_ms=50) == 0.5
    assert mouth_value(envelope, 120.0, frame_ms=50) == 1.0


def test_mouth_value_is_zero_outside_the_envelope() -> None:
    """播完就该闭嘴，不该卡在最后一个值上张着嘴。"""
    assert mouth_value((1.0,), 5_000.0, frame_ms=50) == 0.0
    assert mouth_value((1.0,), -1.0, frame_ms=50) == 0.0
    assert mouth_value((), 0.0, frame_ms=50) == 0.0


def test_mouth_driver_opens_faster_than_it_closes() -> None:
    driver = MouthDriver()
    opened = driver.update(1.0, 0.1)
    closed = driver.update(0.0, 0.1)

    assert opened == 1.0
    assert closed == pytest.approx(0.1)  # release 9/秒 × 0.1 秒


def test_mouth_driver_never_overshoots() -> None:
    driver = MouthDriver()

    assert driver.update(1.0, 0.001) == pytest.approx(0.018)
    assert driver.update(1.0, 10.0) == 1.0


def test_mouth_driver_clamps_the_target() -> None:
    driver = MouthDriver()

    assert driver.update(5.0, 1.0) == 1.0
    assert driver.update(-3.0, 1.0) == 0.0


def test_mouth_driver_reset_closes_immediately() -> None:
    driver = MouthDriver(value=0.8)

    driver.reset()

    assert driver.value == 0.0
