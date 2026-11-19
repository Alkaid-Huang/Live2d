"""渲染进程与主进程之间的消息。

两个方向，都是普通 dataclass，``type`` 是类属性：

- 主进程 → 渲染进程：``PlayAudioCommand`` / ``StopAudioCommand`` /
  ``SetEmotionCommand`` / ``QuitCommand``
- 渲染进程 → 主进程：``RendererReadyMessage`` / ``RendererFailedMessage`` /
  ``AudioStartedMessage`` / ``AudioIdleMessage``

跨进程只传普通字典，不传对象。序列化格式显式写在 ``to_payload`` / ``from_payload``
里——同一份字典就是将来 WebSocket 帧的 ``data``。

这个模块不 import pygame、也不 import live2d；它只依赖 ``contracts``。
"""

from __future__ import annotations

from collections.abc import Mapping
from dataclasses import dataclass, fields
from typing import ClassVar, TypeAlias

from contracts import ErrorEvent, Event, TtsStateEvent

#: 渲染进程回传 ``renderer.failed`` 时使用的错误码。
LIVE2D_LOAD_FAILED = "live2d_load_failed"


@dataclass(frozen=True, slots=True)
class PlayAudioCommand:
    """让渲染进程播一段音频。字段与 ``TtsChunkEvent`` 一致。

    Attributes:
        turn_id: 所属回合的 id。
        segment_index: 本片序号，从 0 开始。
        segment_total: 本回合总片数，大于 0。
        path: 音频文件路径（字符串）。
        format: 音频格式，目前恒为 ``"mp3"``。

    Example:
        ```python
        PlayAudioCommand(
            turn_id="9f3c", segment_index=0, segment_total=1,
            path="tmp_audio/9f3c-0.mp3", format="mp3",
        ).to_payload()
        # {'type': 'play_audio', 'turn_id': '9f3c', 'segment_index': 0, ...}
        ```
    """

    turn_id: str
    segment_index: int
    segment_total: int
    path: str
    format: str
    type: ClassVar[str] = "play_audio"

    def to_payload(self) -> dict[str, object]:
        """摊平成可跨进程传输的字典。

        Returns:
            ``{"type": "play_audio", ...}``，值都是 JSON 可序列化的基本类型。
        """
        return _as_payload(self)


@dataclass(frozen=True, slots=True)
class StopAudioCommand:
    """立刻停止播放、口型归位，并丢弃该回合的待播分片。

    Attributes:
        turn_id: 要停止的回合。空串表示**全局停止**，不管哪个回合都停。

    Example:
        ```python
        StopAudioCommand(turn_id="").to_payload()
        # {'type': 'stop_audio', 'turn_id': ''}
        ```
    """

    turn_id: str
    type: ClassVar[str] = "stop_audio"

    def to_payload(self) -> dict[str, object]:
        """摊平成可跨进程传输的字典。

        Returns:
            ``{"type": "stop_audio", "turn_id": ...}``。
        """
        return _as_payload(self)


@dataclass(frozen=True, slots=True)
class SetEmotionCommand:
    """换表情并按情感播一个动作。

    Attributes:
        turn_id: 所属回合的 id。
        label: 情感标签（中文），取值见 ``emotion.EmotionLabel``。

    Example:
        ```python
        SetEmotionCommand(turn_id="9f3c", label="开心").to_payload()
        # {'type': 'set_emotion', 'turn_id': '9f3c', 'label': '开心'}
        ```
    """

    turn_id: str
    label: str
    type: ClassVar[str] = "set_emotion"

    def to_payload(self) -> dict[str, object]:
        """摊平成可跨进程传输的字典。

        Returns:
            ``{"type": "set_emotion", "turn_id": ..., "label": ...}``。
        """
        return _as_payload(self)


@dataclass(frozen=True, slots=True)
class QuitCommand:
    """让渲染子进程收尾退出。

    Example:
        ```python
        QuitCommand().to_payload()
        # {'type': 'quit'}
        ```
    """

    type: ClassVar[str] = "quit"

    def to_payload(self) -> dict[str, object]:
        """摊平成可跨进程传输的字典。

        Returns:
            ``{"type": "quit"}``。
        """
        return _as_payload(self)


#: 主进程能发给渲染进程的全部命令。
Command: TypeAlias = PlayAudioCommand | StopAudioCommand | SetEmotionCommand | QuitCommand


@dataclass(frozen=True, slots=True)
class RendererReadyMessage:
    """模型加载成功，窗口已经在画了。

    Attributes:
        model_path: 实际加载的模型 json 路径。

    Note:
        不翻译成任何事件，它只是启动期的运维信号。
    """

    model_path: str
    type: ClassVar[str] = "renderer.ready"


@dataclass(frozen=True, slots=True)
class RendererFailedMessage:
    """渲染进程起不来，或模型加载失败。

    Attributes:
        code: 错误码，目前恒为 ``live2d_load_failed``。
        message: 给人看的原因。

    Note:
        收到之后界面退化成"无模型展示"，不退出程序。
    """

    code: str
    message: str
    type: ClassVar[str] = "renderer.failed"


@dataclass(frozen=True, slots=True)
class AudioStartedMessage:
    """某一段音频开始播放。

    Attributes:
        turn_id: 所属回合的 id。
        segment_index: 这一段的序号。
    """

    turn_id: str
    segment_index: int
    type: ClassVar[str] = "audio.started"


@dataclass(frozen=True, slots=True)
class AudioIdleMessage:
    """播放队列排空，没有音频在响。

    Attributes:
        turn_id: 最后播完那一段所属的回合。
    """

    turn_id: str
    type: ClassVar[str] = "audio.idle"


#: 渲染进程能回传给主进程的全部消息。
RendererMessage: TypeAlias = (
    RendererReadyMessage | RendererFailedMessage | AudioStartedMessage | AudioIdleMessage
)


def _as_payload(item: Command | RendererMessage) -> dict[str, object]:
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

    未知的额外字段会被忽略，以允许前向兼容。

    Args:
        payload: 从命令队列取到的字典。

    Returns:
        对应的命令对象。

    Raises:
        ValueError: ``type`` 未知，或必需字段缺失、类型不对。

    Example:
        ```python
        cmd = command_from_payload({"type": "stop_audio", "turn_id": ""})
        assert cmd == StopAudioCommand(turn_id="")
        ```
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


def message_from_payload(payload: Mapping[str, object]) -> RendererMessage:
    """把渲染进程回传的字典还原成消息。

    Args:
        payload: 从回传队列取到的字典。

    Returns:
        对应的消息对象。

    Raises:
        ValueError: ``type`` 未知，或必需字段缺失、类型不对。

    Example:
        ```python
        msg = message_from_payload({"type": "audio.idle", "turn_id": "9f3c"})
        assert msg == AudioIdleMessage(turn_id="9f3c")
        ```
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


def message_to_payload(message: RendererMessage) -> dict[str, object]:
    """把回传消息摊平成字典，交给队列。

    Args:
        message: 渲染进程要回传的消息。

    Returns:
        ``{"type": ..., ...}`` 形式的字典。

    Example:
        ```python
        message_to_payload(AudioIdleMessage(turn_id="9f3c"))
        # {'type': 'audio.idle', 'turn_id': '9f3c'}
        ```
    """
    return _as_payload(message)


def message_to_events(message: RendererMessage) -> tuple[Event, ...]:
    """把回传消息翻译成主进程的事件。

    - ``audio.started`` → ``tts.state(playing)``
    - ``audio.idle`` → ``tts.state(idle)``
    - ``renderer.failed`` → ``error``（``turn_id`` 为空串：启动失败不属于任何回合）
    - ``renderer.ready`` → 没有对应事件

    Args:
        message: 渲染进程回传的消息。

    Returns:
        零个或一个事件；``renderer.ready`` 返回空元组。

    Example:
        ```python
        message_to_events(AudioStartedMessage(turn_id="9f3c", segment_index=0))
        # (TtsStateEvent(turn_id='9f3c', state='playing', detail=''),)
        ```
    """
    if isinstance(message, AudioStartedMessage):
        return (TtsStateEvent(turn_id=message.turn_id, state="playing"),)
    if isinstance(message, AudioIdleMessage):
        return (TtsStateEvent(turn_id=message.turn_id, state="idle"),)
    if isinstance(message, RendererFailedMessage):
        return (ErrorEvent(turn_id="", code=message.code, message=message.message),)
    return ()
