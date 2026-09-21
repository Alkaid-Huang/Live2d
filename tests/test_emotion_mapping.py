"""emotion.mapping 的测试：映射表完整性、回落与抽象性。"""

from __future__ import annotations

import logging

import pytest

from emotion import EMOTION_MAPPING, EmotionCue, EmotionLabel, resolve


def test_mapping_covers_m1_labels() -> None:
    assert set(EMOTION_MAPPING) == {
        EmotionLabel.HAPPINESS,
        EmotionLabel.SADNESS,
        EmotionLabel.ANGER,
        EmotionLabel.NEUTRAL,
    }


def test_mapping_outputs_are_strings() -> None:
    """映射表只输出抽象名字，不 import、也不输出渲染库的参数。"""
    for cue in EMOTION_MAPPING.values():
        assert isinstance(cue, EmotionCue)
        assert isinstance(cue.motion_group, str)
        assert isinstance(cue.expression, str)


def test_resolve_returns_mapped_cue() -> None:
    assert resolve(EmotionLabel.HAPPINESS) is EMOTION_MAPPING[EmotionLabel.HAPPINESS]


def test_resolve_unmapped_falls_back_to_neutral(caplog: pytest.LogCaptureFixture) -> None:
    with caplog.at_level(logging.WARNING):
        cue = resolve(EmotionLabel.SURPRISE)

    assert cue is EMOTION_MAPPING[EmotionLabel.NEUTRAL]
    assert any("未映射" in record.message for record in caplog.records)
