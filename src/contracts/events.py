"""跨模块、跨界面传递的事件。

这一层是叶子模块：只 import 标准库，不 import 项目里的任何实现模块。
所有事件的形状与语义见 ``docs/reference.md``，这里只维护定义。
"""

from __future__ import annotations

from collections.abc import Callable
from dataclasses import asdict, dataclass
from typing import ClassVar, Literal

#: 语音状态。四个取值覆盖"合成"与"播放"两件事。
TtsState = Literal["idle", "synthesizing", "playing", "failed"]

#: 回合终止的原因。
CancelReason = Literal["user_new_message", "user_stop", "error"]


@dataclass(frozen=True, slots=True)
class Event:
    """所有事件的基类。

    子类用 ``type`` 类属性标注种类，``turn_id`` 标识所属回合。
    ``turn_id`` 为空串表示这条事件不属于任何回合（只有启动期错误会这样）。

    Attributes:
        turn_id: 所属回合的 id。

    Example:
        ```python
        event = LlmTokenEvent(turn_id="9f3c", text="你")
        event.to_frame()
        # {'type': 'llm.token', 'turn_id': '9f3c', 'data': {'text': '你'}}
        ```
    """

    turn_id: str
    type: ClassVar[str] = "event"

    def to_frame(self) -> dict[str, object]:
        """转成 ``{"type": ..., "turn_id": ..., "data": {...}}``。

        ``turn_id`` 只在帧顶层，不重复进 ``data``。这是将来 WebSocket 帧的形状。

        Returns:
            可以直接 JSON 序列化的字典。

        Example:
            ```python
            TurnDoneEvent(turn_id="9f3c").to_frame()
            # {'type': 'turn.done', 'turn_id': '9f3c', 'data': {}}
            ```
        """
        data = {name: value for name, value in asdict(self).items() if name != "turn_id"}
        return {"type": self.type, "turn_id": self.turn_id, "data": data}


#: 事件的接收方。runtime 只管调用它，不关心对面是 Qt 信号还是跨进程队列。
EventSink = Callable[[Event], None]


@dataclass(frozen=True, slots=True)
class TurnStartEvent(Event):
    """新回合开始。它是本回合第一条事件。

    Attributes:
        user_text: 用户这一轮的原文（已去首尾空白）。

    Example:
        ```python
        TurnStartEvent(turn_id="9f3c", user_text="在吗")
        ```
    """

    user_text: str
    type: ClassVar[str] = "turn.start"


@dataclass(frozen=True, slots=True)
class LlmTokenEvent(Event):
    """一段增量文本。界面拿它做逐字显示。

    Attributes:
        text: 本次增量。可能为空串以外的任意长度，调用方按顺序拼接。

    Example:
        ```python
        LlmTokenEvent(turn_id="9f3c", text="你好")
        ```
    """

    text: str
    type: ClassVar[str] = "llm.token"


@dataclass(frozen=True, slots=True)
class LlmDoneEvent(Event):
    """回复生成完毕。

    Attributes:
        finish_reason: 结束原因。目前恒为 ``"stop"``。

    Note:
        当前的 router 只产出文本增量，没有把 Provider 的结束原因带上来。
    """

    finish_reason: str
    type: ClassVar[str] = "llm.done"


@dataclass(frozen=True, slots=True)
class EmotionDetectedEvent(Event):
    """本回合的情感标签。

    Attributes:
        label: 情感标签（中文），取值见 ``emotion.EmotionLabel``。
        source: 判断来源，目前恒为 ``"rules"``。

    Example:
        ```python
        EmotionDetectedEvent(turn_id="9f3c", label="开心", source="rules")
        ```
    """

    label: str
    source: str
    type: ClassVar[str] = "emotion.detected"


@dataclass(frozen=True, slots=True)
class TtsStateEvent(Event):
    """语音状态变化。

    Attributes:
        state: 四个取值之一，见 ``TtsState``。
        detail: 失败原因；成功时为空串。

    Note:
        ``synthesizing`` 与 ``failed`` 由 runtime 发出；``playing`` 与 ``idle``
        由渲染进程回传、经 ``stage.protocol.message_to_events()`` 翻译而来。
    """

    state: TtsState
    detail: str = ""
    type: ClassVar[str] = "tts.state"


@dataclass(frozen=True, slots=True)
class TtsChunkEvent(Event):
    """一段音频就绪，可以播放。

    Attributes:
        segment_index: 本片序号，从 0 开始。
        segment_total: 本回合总片数，大于 0。
        path: 音频文件路径（字符串，不是 ``Path``，因为事件要能直接序列化）。
        format: 音频格式，目前恒为 ``"mp3"``。

    Example:
        ```python
        TtsChunkEvent(
            turn_id="9f3c", segment_index=0, segment_total=2,
            path="tmp_audio/9f3c-0.mp3", format="mp3",
        )
        ```
    """

    segment_index: int
    segment_total: int
    path: str
    format: str
    type: ClassVar[str] = "tts.chunk"


@dataclass(frozen=True, slots=True)
class TurnCancelledEvent(Event):
    """本回合作废。此后不再产生该 ``turn_id`` 的任何编排事件。

    Attributes:
        reason: 取消原因，见 ``CancelReason``。

    Note:
        播放阶段被打断时**不**发这个事件，只停音频。
    """

    reason: CancelReason
    type: ClassVar[str] = "turn.cancelled"


@dataclass(frozen=True, slots=True)
class TurnDoneEvent(Event):
    """编排结束。

    Note:
        **不代表播放结束**：音频可能仍在渲染进程的队列里。
        它之后仍可能收到同 ``turn_id`` 的 ``tts.state(playing|idle)``。

    Example:
        ```python
        TurnDoneEvent(turn_id="9f3c")
        ```
    """

    type: ClassVar[str] = "turn.done"


@dataclass(frozen=True, slots=True)
class ErrorEvent(Event):
    """出错。

    Attributes:
        code: 错误码，取值见 ``docs/reference.md`` 的错误码表。
        message: 给用户看的说明。

    Example:
        ```python
        ErrorEvent(turn_id="9f3c", code="llm_timeout", message="LLM 请求超时")
        ```
    """

    code: str
    message: str
    type: ClassVar[str] = "error"
