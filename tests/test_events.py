"""events 模块的测试：类型标签、帧形状，以及和契约的不许分叉。"""

from __future__ import annotations

import dataclasses

import pytest

import events
from events import (
    Event,
    LlmDoneEvent,
    LlmTokenEvent,
    TtsStateEvent,
    TurnDoneEvent,
)
from tts.base import TtsState as TtsLayerState

#: docs/contracts.md 第 2 节的事件类型表。少一个多一个都算契约被改了。
CONTRACT_EVENT_TYPES = {
    "turn.start",
    "llm.token",
    "llm.done",
    "emotion.detected",
    "tts.state",
    "tts.chunk",
    "turn.cancelled",
    "turn.done",
    "error",
}


def test_event_types_match_the_contract() -> None:
    declared = {cls.type for cls in Event.__subclasses__()}

    assert declared == CONTRACT_EVENT_TYPES


def test_frame_shape() -> None:
    frame = LlmTokenEvent(turn_id="t1", text="你").to_frame()

    assert frame == {"type": "llm.token", "turn_id": "t1", "data": {"text": "你"}}


def test_frame_of_event_without_fields_has_empty_data() -> None:
    frame = TurnDoneEvent(turn_id="t1").to_frame()

    assert frame == {"type": "turn.done", "turn_id": "t1", "data": {}}


def test_turn_id_is_not_duplicated_into_data() -> None:
    frame = LlmDoneEvent(turn_id="t1", finish_reason="stop").to_frame()

    assert "turn_id" not in frame["data"]
    assert frame["data"] == {"finish_reason": "stop"}


def test_tts_state_values_match_the_tts_layer() -> None:
    """events 里这份 TtsState 是 tts.base 那一份的副本，不许悄悄分叉。"""
    from typing import get_args

    assert set(get_args(events.TtsState)) == set(get_args(TtsLayerState))


def test_cancel_reasons_match_the_contract() -> None:
    from typing import get_args

    assert set(get_args(events.CancelReason)) == {"user_new_message", "user_stop", "error"}


def test_events_are_immutable() -> None:
    """事件是不可变的：改字段应该是错误，而不是静默改掉别人手上那一份。"""
    event = TtsStateEvent(turn_id="t1", state="synthesizing")

    with pytest.raises(dataclasses.FrozenInstanceError):
        event.state = "idle"  # type: ignore[misc]
