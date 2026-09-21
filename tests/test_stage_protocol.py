"""渲染进程消息协议的测试。

这一层是跨进程的边界：字典里少一个字段、类型不对，对面就会崩在渲染循环里，
所以在进队列之前就要拦住。
"""

from __future__ import annotations

from typing import Any

import pytest

from stage.protocol import (
    AudioIdleMessage,
    AudioStartedMessage,
    PlayAudioCommand,
    QuitCommand,
    RendererFailedMessage,
    RendererReadyMessage,
    SetEmotionCommand,
    StopAudioCommand,
    command_from_payload,
    message_from_payload,
    message_to_events,
    message_to_payload,
)


def test_play_audio_command_round_trips() -> None:
    command = PlayAudioCommand(
        turn_id="t1",
        segment_index=1,
        segment_total=3,
        path="tmp_audio/t1-1.mp3",
        format="mp3",
    )

    payload = command.to_payload()

    assert payload["type"] == "play_audio"
    assert command_from_payload(payload) == command


def test_stop_audio_command_round_trips() -> None:
    command = StopAudioCommand(turn_id="t1")

    assert command_from_payload(command.to_payload()) == command


def test_set_emotion_command_round_trips() -> None:
    command = SetEmotionCommand(turn_id="t1", label="开心")

    payload = command.to_payload()

    assert payload["type"] == "set_emotion"
    assert command_from_payload(payload) == command


def test_quit_command_round_trips() -> None:
    command = QuitCommand()

    payload = command.to_payload()

    assert payload == {"type": "quit"}
    assert command_from_payload(payload) == command


@pytest.mark.parametrize(
    "message",
    [
        RendererReadyMessage(model_path="models/hiyori/Hiyori.model3.json"),
        RendererFailedMessage(code="live2d_load_failed", message="没有模型"),
        AudioStartedMessage(turn_id="t1", segment_index=0),
        AudioIdleMessage(turn_id="t1"),
    ],
)
def test_messages_round_trip(message: Any) -> None:
    payload = message_to_payload(message)

    assert payload["type"] == message.type
    assert message_from_payload(payload) == message


def test_unknown_command_kind_is_rejected() -> None:
    with pytest.raises(ValueError, match="未知的渲染命令"):
        command_from_payload({"type": "dance"})


def test_unknown_message_kind_is_rejected() -> None:
    with pytest.raises(ValueError, match="未知的渲染回传"):
        message_from_payload({"type": "audio.paused"})


def test_missing_field_is_rejected() -> None:
    payload = PlayAudioCommand(
        turn_id="t1",
        segment_index=0,
        segment_total=1,
        path="a.mp3",
        format="mp3",
    ).to_payload()
    payload.pop("path")

    with pytest.raises(ValueError, match="path"):
        command_from_payload(payload)


def test_boolean_is_not_accepted_as_an_index() -> None:
    """bool 是 int 的子类，不挡掉的话 True 会被当成序号 1 混过去。"""
    payload = {
        "type": "play_audio",
        "turn_id": "t1",
        "segment_index": True,
        "segment_total": False,
        "path": "a.mp3",
        "format": "mp3",
    }

    with pytest.raises(ValueError, match="segment_index"):
        command_from_payload(payload)


def test_message_to_events_maps_playback_state() -> None:
    """回传消息 → 主进程事件（docs/contracts.md 第 2、4 节）。"""
    started = message_to_events(AudioStartedMessage(turn_id="t1", segment_index=0))
    idle = message_to_events(AudioIdleMessage(turn_id="t1"))

    assert [(event.type, event.turn_id) for event in started] == [("tts.state", "t1")]
    assert started[0].state == "playing"  # type: ignore[attr-defined]
    assert idle[0].state == "idle"  # type: ignore[attr-defined]


def test_failure_becomes_an_error_event_without_a_turn() -> None:
    events = message_to_events(RendererFailedMessage(code="live2d_load_failed", message="没有模型"))

    assert len(events) == 1
    assert events[0].type == "error"
    assert events[0].turn_id == ""
    assert events[0].code == "live2d_load_failed"  # type: ignore[attr-defined]


def test_ready_message_has_no_event() -> None:
    """窗口就绪只是运维信号，不进事件流。"""
    assert message_to_events(RendererReadyMessage(model_path="m.model3.json")) == ()
