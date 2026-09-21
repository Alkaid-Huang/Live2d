"""emotion.rules 的测试：纯函数，不发网络，不读配置。"""

from __future__ import annotations

import pytest

from emotion import EmotionLabel, detect


@pytest.mark.parametrize(
    ("text", "expected"),
    [
        ("哈哈，太好了！", EmotionLabel.HAPPINESS),
        ("我有点难过", EmotionLabel.SADNESS),
        ("气死我了", EmotionLabel.ANGER),
        ("居然会这样", EmotionLabel.SURPRISE),
        ("我好害怕", EmotionLabel.FEAR),
        ("真恶心", EmotionLabel.DISGUST),
    ],
)
def test_detect_keywords(text: str, expected: EmotionLabel) -> None:
    assert detect(text) is expected


def test_empty_and_blank_return_neutral() -> None:
    assert detect("") is EmotionLabel.NEUTRAL
    assert detect("   ") is EmotionLabel.NEUTRAL


def test_unknown_text_returns_neutral() -> None:
    assert detect("今天天气不错") is EmotionLabel.NEUTRAL


def test_priority_when_multiple_match() -> None:
    """「又生气又害怕」同时命中生气和害怕，害怕优先级更高。"""
    assert detect("又生气又害怕") is EmotionLabel.FEAR


def test_negative_is_not_understood() -> None:
    """记录在案的局限：规则不看否定，M2 换分类模型再解决。"""
    assert detect("一点也不开心") is EmotionLabel.HAPPINESS
