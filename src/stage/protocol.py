"""渲染进程与主进程之间的消息（docs/contracts.md 第 4 节）。

两个方向：

- 主进程 → 渲染进程：``PlayAudioCommand`` / ``StopAudioCommand`` /
  ``SetEmotionCommand`` / ``QuitCommand``
- 渲染进程 → 主进程：``RendererReadyMessage`` / ``RendererFailedMessage`` /
  ``AudioStartedMessage`` / ``AudioIdleMessage``

跨进程只传普通字典，不传对象：格式显式写在 ``to_payload`` / ``from_payload`` 里，
将来转 Web 时同一份字典就是 WebSocket 帧的 data，不用再设计一遍协议。

这个模块不 import pygame、也不 import live2d。
"""

from __future__ import annotations

from collections.abc import Mapping
from dataclasses import dataclass, fields
from typing import ClassVar, TypeAlias

from events import ErrorEvent, Event, TtsStateEvent

#: 渲染进程回传 ``renderer.failed`` 时的错误码，取值来自 docs/contracts.md 第 5 节。
LIVE2D_LOAD_FAILED = "live2d_load_failed"


@dataclass(frozen=True, slots=True)
class PlayAudioCommand:
    """让渲染进程播一段音频。字段与 TtsChunkEvent 一致。"""

    turn_id: str
    segment_index: int
    segment_total: int
    path: str
    format: str
    type: ClassVar[str] = "play_audio"

    def to_payload(self) -> dict[str, object]:
        return _as_payload(self)


@dataclass(frozen=True, slots=True)
class StopAudioCommand:
    """立刻停止播放、口型归位。

    ``turn_id`` 为空串表示"不管哪一个回合，全停"（退出或强制复位时用）。
    """

    turn_id: str
    type: ClassVar[str] = "stop_audio"

    def to_payload(self) -> dict[str, object]:
        return _as_payload(self)


@dataclass(frozen=True, slots=True)
class SetEmotionCommand:
    """换表情与动作。``label`` 是 EmotionDetectedEvent 里的中文标签。"""

    turn_id: str
    label: str
    type: ClassVar[str] = "set_emotion"

    def to_payload(self) -> dict[str, object]:
        return _as_payload(self)


@dataclass(frozen=True, slots=True)
class QuitCommand:
    """退出渲染子进程。"""

    type: ClassVar[str] = "quit"

    def to_payload(self) -> dict[str, object]:
        return _as_payload(self)


Command: TypeAlias = PlayAudioCommand | StopAudioCommand | SetEmotionCommand | QuitCommand


@dataclass(frozen=True, slots=True)
class RendererReadyMessage:
    """模型加载成功，窗口已经在画了。"""

    model_path: str
    type: ClassVar[str] = "renderer.ready"


@dataclass(frozen=True, slots=True)
class RendererFailedMessage:
    """渲染进程起不来或模型加载失败。

    收到之后界面应该退化成"无模型展示"，而不是退出程序（docs/contracts.md 第 5 节）。
    """

    code: str
    message: str
    type: ClassVar[str] = "renderer.failed"


@dataclass(frozen=True, slots=True)
class AudioStartedMessage:
    """某一段音频开始播放。"""

    turn_id: str
    segment_index: int
    type: ClassVar[str] = "audio.started"


@dataclass(frozen=True, slots=True)
class AudioIdleMessage:
    """播放队列排空了，没有音频在响。``turn_id`` 是最后播完那一段所属的回合。"""

    turn_id: str
    type: ClassVar[str] = "audio.idle"


Message: TypeAlias = (
    RendererReadyMessage | RendererFailedMessage | AudioStartedMessage | AudioIdleMessage
)


def _as_payload(item: Command | Message) -> dict[str, object]:
    """把消息/命令摊成字典。``type`` 是类属性，不进 dataclass 字段，所以单独加上。"""
    payload: dict[str, object] = {"type": item.type}
    payload.update({field.name: getattr(item, field.name) for field in fields(item)})
    return payload


def _require_str(payload: Mapping[str, object], key: str) -> str:
    value = payload.get(key)
    if not isinstance(value, str):
        raise ValueError(f"字段 {key} 必须是字符串，收到 {value!r}")
    return value


def _require_int(payload: Mapping[str, object], key: str) -> int:
    value = payload.get(key)
    # bool 是 int 的子类，显式挡掉，免得 True 被当成 1 混过序号校验。
    if isinstance(value, bool) or not isinstance(value, int):
        raise ValueError(f"字段 {key} 必须是整数，收到 {value!r}")
    return value


def _require_type(payload: Mapping[str, object]) -> str:
    return _require_str(payload, "type")


def command_from_payload(payload: Mapping[str, object]) -> Command:
    """把队列里取到的字典还原成命令。

    Raises:
        ValueError: 种类未知，或字段类型不对。
    """
    kind = _require_type(payload)
    if kind == "play_audio":
        return PlayAudioCommand(
            turn_id=_require_str(payload, "turn_id"),
            segment_index=_require_int(payload, "segment_index"),
            segment_total=_require_int(payload, "segment_total"),
            path=_require_str(payload, "path"),
            format=_require_str(payload, "format"),
        )
    if kind == "stop_audio":
        return StopAudioCommand(turn_id=_require_str(payload, "turn_id"))
    if kind == "set_emotion":
        return SetEmotionCommand(
            turn_id=_require_str(payload, "turn_id"),
            label=_require_str(payload, "label"),
        )
    if kind == "quit":
        return QuitCommand()
    raise ValueError(f"未知的渲染命令：{kind}")


def message_from_payload(payload: Mapping[str, object]) -> Message:
    """把渲染进程回传的字典还原成消息。

    Raises:
        ValueError: 种类未知，或字段类型不对。
    """
    kind = _require_type(payload)
    if kind == "renderer.ready":
        return RendererReadyMessage(model_path=_require_str(payload, "model_path"))
    if kind == "renderer.failed":
        return RendererFailedMessage(
            code=_require_str(payload, "code"),
            message=_require_str(payload, "message"),
        )
    if kind == "audio.started":
        return AudioStartedMessage(
            turn_id=_require_str(payload, "turn_id"),
            segment_index=_require_int(payload, "segment_index"),
        )
    if kind == "audio.idle":
        return AudioIdleMessage(turn_id=_require_str(payload, "turn_id"))
    raise ValueError(f"未知的渲染回传：{kind}")


def message_to_payload(message: Message) -> dict[str, object]:
    """消息 → 字典。"""
    return _as_payload(message)


def message_to_events(message: Message) -> tuple[Event, ...]:
    """把回传消息翻译成主进程的事件（docs/contracts.md 第 2、4 节）。

    - ``audio.started`` → ``tts.state(playing)``
    - ``audio.idle`` → ``tts.state(idle)``
    - ``renderer.failed`` → ``error``（``turn_id`` 为空串：启动失败不属于任何回合）
    - ``renderer.ready`` → 没有对应事件，它只是"窗口起来了"的运维信号
    """
    if isinstance(message, AudioStartedMessage):
        return (TtsStateEvent(turn_id=message.turn_id, state="playing"),)
    if isinstance(message, AudioIdleMessage):
        return (TtsStateEvent(turn_id=message.turn_id, state="idle"),)
    if isinstance(message, RendererFailedMessage):
        return (ErrorEvent(turn_id="", code=message.code, message=message.message),)
    return ()


#: 事件里 turn_id 为空串的含义：这条事件不属于任何回合（只有启动期的问题如此）。
NO_TURN_ID = ""
