"""情感提示 → 动作组 / 表情名的选择与回落。"""

from __future__ import annotations

import logging

import pytest

from stage.cues import (
    ModelCapabilities,
    normalize_capabilities,
    resolve_label,
    select_expression,
    select_motion,
)


def test_known_label_maps_through_the_shared_table() -> None:
    cue = resolve_label("开心")

    assert cue.motion_group == "happiness"
    assert cue.expression == "smile"


def test_label_without_a_mapping_falls_back_to_neutral(caplog: pytest.LogCaptureFixture) -> None:
    """惊讶/害怕/厌恶在映射表里没有键，按契约回落到中性并记日志。"""
    with caplog.at_level(logging.WARNING):
        cue = resolve_label("惊讶")

    assert cue == resolve_label("中性")
    assert "回落到中性" in caplog.text


def test_unknown_label_string_falls_back_to_neutral(caplog: pytest.LogCaptureFixture) -> None:
    """跨进程传来的标签可能是别的版本写进来的，认不出也不许崩。"""
    with caplog.at_level(logging.WARNING):
        cue = resolve_label("困惑")

    assert cue == resolve_label("中性")
    assert "认不出的情感标签" in caplog.text


def test_normalize_accepts_a_dict_of_groups() -> None:
    capabilities = normalize_capabilities({"Idle": 1, "TapBody": 2}, None)

    assert capabilities.motion_groups == ("Idle", "TapBody")
    assert capabilities.expressions == ()


def test_normalize_accepts_a_list_and_filters_junk() -> None:
    capabilities = normalize_capabilities(["Idle", "", " Idle ", 42, "  "], ["F01"])

    assert capabilities.motion_groups == ("Idle",)
    assert capabilities.expressions == ("F01",)


def test_normalize_tolerates_unexpected_shapes() -> None:
    assert normalize_capabilities(None, 3.5) == ModelCapabilities()
    assert normalize_capabilities("Idle", b"F01").motion_groups == ()


def test_motion_match_is_case_insensitive() -> None:
    capabilities = ModelCapabilities(motion_groups=("IDLE",))

    assert capabilities.find_motion("idle") == "IDLE"


def test_select_motion_prefers_the_emotional_group() -> None:
    capabilities = ModelCapabilities(motion_groups=("Idle", "happiness"))

    assert select_motion(capabilities, resolve_label("开心")) == "happiness"


def test_select_motion_falls_back_to_idle(caplog: pytest.LogCaptureFixture) -> None:
    """免费素材的模型通常只有待机动作，这时退回待机而不是什么都不做。"""
    capabilities = ModelCapabilities(motion_groups=("Idle",))

    with caplog.at_level(logging.DEBUG):
        selected = select_motion(capabilities, resolve_label("开心"))

    assert selected == "Idle"


def test_select_motion_returns_none_when_the_model_has_no_motions(
    caplog: pytest.LogCaptureFixture,
) -> None:
    with caplog.at_level(logging.WARNING):
        selected = select_motion(ModelCapabilities(), resolve_label("开心"))

    assert selected is None
    assert "没有任何可用动作组" in caplog.text


def test_select_expression_returns_none_when_missing(caplog: pytest.LogCaptureFixture) -> None:
    with caplog.at_level(logging.DEBUG):
        selected = select_expression(ModelCapabilities(expressions=("F01",)), resolve_label("开心"))

    assert selected is None
    assert "没有表情 smile" in caplog.text


def test_select_expression_finds_a_match() -> None:
    capabilities = ModelCapabilities(expressions=("F01", "smile"))

    assert select_expression(capabilities, resolve_label("开心")) == "smile"
