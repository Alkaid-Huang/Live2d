"""统一事件类型（docs/contracts.md 第 2、3 节）。

跨进程、跨界面只传这一种东西：每个事件都是 frozen dataclass，都带 ``turn_id``
和 ``type``；``to_frame()`` 给出契约第 7 节承诺的 WebSocket 帧形状——将来转 Web
形态时，序列化只需要写这一处。

这一层是叶子模块：不 import 项目里的任何其他模块，也不 import 网络或 GUI 库
（AGENTS.md 硬约束 1）。
"""

from __future__ import annotations

from collections.abc import Callable
from dataclasses import asdict, dataclass
from typing import ClassVar, Literal

#: TTS 状态。取值必须与 tts.base.TtsState 一致——那边是同一份词汇，
#: tests/test_events.py 里有一条测试盯着它们不许分叉。
TtsState = Literal["idle", "synthesizing", "playing", "failed"]

#: 回合终止的原因，见 docs/contracts.md 第 3 节。
CancelReason = Literal["user_new_message", "user_stop", "error"]


@dataclass(frozen=True, slots=True)
class Event:
    """所有事件的基类。

    ``type`` 是类属性而不是字段：它是事件的种类标签，不随实例变化，
    也不该出现在 ``to_frame()`` 的 data 里。
    """

    turn_id: str
    type: ClassVar[str] = "event"

    def to_frame(self) -> dict[str, object]:
        """转成契约第 7 节的帧：``{"type": ..., "turn_id": ..., "data": {...}}``。"""
        data = {name: value for name, value in asdict(self).items() if name != "turn_id"}
        return {"type": self.type, "turn_id": self.turn_id, "data": data}


#: 事件的接收方。runtime 只管调用它，不关心对面是 Qt 信号还是跨进程队列。
EventSink = Callable[[Event], None]


@dataclass(frozen=True, slots=True)
class TurnStartEvent(Event):
    """一个新回合开始。"""

    user_text: str
    type: ClassVar[str] = "turn.start"


@dataclass(frozen=True, slots=True)
class LlmTokenEvent(Event):
    """一段增量文本。界面拿它做逐字显示。"""

    text: str
    type: ClassVar[str] = "llm.token"


@dataclass(frozen=True, slots=True)
class LlmDoneEvent(Event):
    """回复生成完毕。

    ``finish_reason`` 目前恒为 ``"stop"``：M1 的 router 只产出文本增量，没有把
    Provider 的结束原因带上来（见 docs/contracts.md 第 4 节）。
    """

    finish_reason: str
    type: ClassVar[str] = "llm.done"


@dataclass(frozen=True, slots=True)
class EmotionDetectedEvent(Event):
    """本回合的情感标签。

    ``label`` 是 EmotionLabel 的值（中文名），``source`` 是判断来源，M1 恒为
    ``"rules"``，M2 换成分类模型后会有别的取值。

    事件里只带标签、不带动作组和表情名：标签到动作组的解析由渲染进程自己做
    （docs/contracts.md 第 4 节），因为它才知道当前模型有哪些动作可用。
    """

    label: str
    source: str
    type: ClassVar[str] = "emotion.detected"


@dataclass(frozen=True, slots=True)
class TtsStateEvent(Event):
    """语音状态变化。

    M1-4 只发 runtime 能诚实知道的两种：``synthesizing``（开始合成）和
    ``failed``（合成失败）。``playing`` / ``idle`` 说的是播放状态，只有渲染进程
    知道，等 M1-5 补上回传通道再发。
    """

    state: TtsState
    detail: str = ""
    type: ClassVar[str] = "tts.state"


@dataclass(frozen=True, slots=True)
class TtsChunkEvent(Event):
    """一段音频就绪。

    ``path`` 是字符串而不是 ``Path``：事件要能直接变成 JSON 帧，路径的
    ``Path`` 对象留在 tts 层内部（见 docs/contracts.md 第 4 节）。
    """

    segment_index: int
    segment_total: int
    path: str
    format: str
    type: ClassVar[str] = "tts.chunk"


@dataclass(frozen=True, slots=True)
class TurnCancelledEvent(Event):
    """本回合作废。此后不再产生该 turn_id 的任何事件。"""

    reason: CancelReason
    type: ClassVar[str] = "turn.cancelled"


@dataclass(frozen=True, slots=True)
class TurnDoneEvent(Event):
    """本回合彻底结束。"""

    type: ClassVar[str] = "turn.done"


@dataclass(frozen=True, slots=True)
class ErrorEvent(Event):
    """出错。``code`` 取自 docs/contracts.md 第 5 节的错误码表。"""

    code: str
    message: str
    type: ClassVar[str] = "error"
