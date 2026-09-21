"""播放通道的测试：命令发出去的形状，以及回传消息的解析与容错。"""

from __future__ import annotations

import queue

from stage.channel import RendererChannel
from stage.protocol import (
    AudioStartedMessage,
    PlayAudioCommand,
    QuitCommand,
    SetEmotionCommand,
    StopAudioCommand,
    command_from_payload,
)


class FakeQueue:
    """只用 put / put_nowait / get_nowait 的假队列，替代 multiprocessing.Queue。"""

    def __init__(self) -> None:
        self.items: list[object] = []

    def put(self, item: object) -> None:
        self.items.append(item)

    def put_nowait(self, item: object) -> None:
        self.items.append(item)

    def get_nowait(self) -> object:
        if not self.items:
            raise queue.Empty
        return self.items.pop(0)


def make_channel() -> tuple[RendererChannel, FakeQueue, FakeQueue]:
    commands = FakeQueue()
    messages = FakeQueue()
    return RendererChannel(command_queue=commands, message_queue=messages), commands, messages


def test_play_sends_a_play_command() -> None:
    channel, commands, _ = make_channel()

    channel.play(
        turn_id="t1",
        segment_index=1,
        segment_total=2,
        path="tmp_audio/t1-1.mp3",
        format="mp3",
    )

    command = command_from_payload(commands.items[0])  # type: ignore[arg-type]
    assert command == PlayAudioCommand(
        turn_id="t1",
        segment_index=1,
        segment_total=2,
        path="tmp_audio/t1-1.mp3",
        format="mp3",
    )


def test_stop_sends_a_stop_command() -> None:
    channel, commands, _ = make_channel()

    channel.stop("t1")

    assert command_from_payload(commands.items[0]) == StopAudioCommand(turn_id="t1")  # type: ignore[arg-type]


def test_set_emotion_sends_a_set_emotion_command() -> None:
    channel, commands, _ = make_channel()

    channel.set_emotion(turn_id="t1", label="开心")

    assert command_from_payload(commands.items[0]) == SetEmotionCommand(  # type: ignore[arg-type]
        turn_id="t1", label="开心"
    )


def test_quit_sends_a_quit_command() -> None:
    channel, commands, _ = make_channel()

    channel.quit()

    assert command_from_payload(commands.items[0]) == QuitCommand()  # type: ignore[arg-type]


def test_drain_messages_returns_nothing_when_empty() -> None:
    channel, _, _ = make_channel()

    assert channel.drain_messages() == ()


def test_drain_messages_parses_in_order() -> None:
    channel, _, messages = make_channel()
    messages.put({"type": "audio.started", "turn_id": "t1", "segment_index": 0})
    messages.put({"type": "audio.idle", "turn_id": "t1"})

    drained = channel.drain_messages()

    assert [message.type for message in drained] == ["audio.started", "audio.idle"]
    assert drained[0] == AudioStartedMessage(turn_id="t1", segment_index=0)
    assert channel.drain_messages() == ()


def test_drain_messages_skips_junk_instead_of_crashing() -> None:
    """一条坏消息不该让界面崩掉，丢了它、继续跑。"""
    channel, _, messages = make_channel()
    messages.put("这不是字典")
    messages.put({"type": "audio.paused"})
    messages.put({"type": "audio.idle", "turn_id": "t1"})

    drained = channel.drain_messages()

    assert [message.type for message in drained] == ["audio.idle"]
