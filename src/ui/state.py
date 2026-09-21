"""界面侧的纯逻辑：显示状态、发送排队、延迟打点。

三样东西放在同一个文件里，是因为它们都只服务界面、都只有几十行，而且都
**不 import Qt** —— 所以 CI 里跑得动。``ui/window.py`` 被 pyproject 的
coverage omit 排除在覆盖率之外，那个文件只许当薄壳：判断逻辑一律放这里。
"""

from __future__ import annotations

import threading
import time
from collections.abc import Callable
from dataclasses import dataclass, field
from typing import Literal

from events import (
    EmotionDetectedEvent,
    ErrorEvent,
    Event,
    LlmDoneEvent,
    LlmTokenEvent,
    TtsChunkEvent,
    TtsStateEvent,
    TurnCancelledEvent,
    TurnDoneEvent,
    TurnStartEvent,
)

EntryRole = Literal["user", "assistant"]
EntryStatus = Literal["streaming", "done", "cancelled"]

IDLE_STATUS = "空闲"

#: tts.state 的取值 → 状态栏文字（docs/contracts.md 第 2 节）。
TTS_STATUS: dict[str, str] = {
    "idle": IDLE_STATUS,
    "synthesizing": "合成语音…",
    "playing": "播放中…",
    "failed": "语音失败",
}

#: 错误码 → 状态栏文字（docs/contracts.md 第 5 节）。
ERROR_STATUS: dict[str, str] = {
    "invalid_request": "配置有问题",
    "live2d_load_failed": "无模型展示",
    "llm_timeout": "模型超时",
    "llm_error": "模型出错",
    "tts_error": "语音失败",
    "cancelled": "已取消",
}


@dataclass
class Entry:
    """对话里的一条消息。

    ``status`` 说的是**这条消息本身**的状态，不是整个回合的状态：
    ``streaming`` 表示字还在往外流，``cancelled`` 表示它被中途打断（这时按
    docs/contracts.md 第 3 节，它也不会进 runtime 的历史）。
    """

    role: EntryRole
    text: str = ""
    status: EntryStatus = "done"


@dataclass
class ConversationView:
    """把事件流翻译成"界面上该显示什么"。

    窗口只照着这些字段画，不许自己判断事件类型——那正是"界面里堆判断"的开端。
    """

    entries: list[Entry] = field(default_factory=list)
    status: str = IDLE_STATUS
    busy: bool = False
    last_emotion: str | None = None
    last_error: str | None = None

    def apply(self, event: Event) -> bool:
        """吃一条事件。返回 False 表示它不影响显示，窗口可以不重画。"""
        if isinstance(event, TurnStartEvent):
            self.entries.append(Entry(role="user", text=event.user_text))
            self.entries.append(Entry(role="assistant", status="streaming"))
            self.busy = True
            self.last_error = None
            self.status = "正在回复…"
            return True

        if isinstance(event, LlmTokenEvent):
            entry = self._streaming_entry()
            if entry is None:
                return False
            entry.text += event.text
            return True

        if isinstance(event, LlmDoneEvent):
            # 文字到这里就完整了。语音还在后面，所以 busy 不动。
            entry = self._streaming_entry()
            if entry is not None:
                entry.status = "done"
            return True

        if isinstance(event, EmotionDetectedEvent):
            self.last_emotion = event.label
            return True

        if isinstance(event, TtsStateEvent):
            self.status = TTS_STATUS.get(event.state, event.state)
            if event.state == "failed":
                detail = f"：{event.detail}" if event.detail else ""
                self.last_error = f"语音合成失败{detail}"
            return True

        if isinstance(event, TtsChunkEvent):
            self.status = f"语音 {event.segment_index + 1}/{event.segment_total}"
            return True

        if isinstance(event, TurnCancelledEvent):
            # 只有"字还没流完"的那种才算被截断；回复已经完整、只是语音失败或
            # 被打断的，文字该照常显示（它也已经进了历史）。
            entry = self._streaming_entry()
            if entry is not None:
                entry.status = "cancelled"
            self.busy = False
            self.status = "出错" if event.reason == "error" else "已打断"
            return True

        if isinstance(event, TurnDoneEvent):
            entry = self._streaming_entry()
            if entry is not None:
                entry.status = "done"
            self.busy = False
            self.status = IDLE_STATUS
            return True

        if isinstance(event, ErrorEvent):
            self.last_error = f"{event.code}：{event.message}"
            self.status = ERROR_STATUS.get(event.code, "出错")
            return True

        return False

    def _streaming_entry(self) -> Entry | None:
        """当前正在写的那条助手消息；没有就返回 None。"""
        if not self.entries:
            return None
        last = self.entries[-1]
        return last if last.role == "assistant" and last.status == "streaming" else None


@dataclass(frozen=True)
class SendDecision:
    """一次发送该怎么处理。两个字段最多只有一个非空。"""

    start_now: str | None = None
    cancel_turn_id: str | None = None


class SendQueue:
    """用户在一回合进行中又发消息时怎么办。

    契约（docs/contracts.md 第 1 节）要求"先 cancel，等 send() 返回再开下一个"，
    所以这里只做决定、不自己开线程。规则：空闲就直接开跑；忙就取消当前回合并
    把新文本记成待发，**后来者覆盖前者**——用户连按三次，只想看到最后一次的回复。
    """

    def __init__(self) -> None:
        self._pending: str | None = None
        self._lock = threading.Lock()

    @property
    def pending(self) -> str | None:
        """当前待发的文本（没有就是 None）。"""
        with self._lock:
            return self._pending

    def submit(self, text: str, *, active_turn_id: str | None) -> SendDecision:
        """用户提交了一条消息，返回该怎么处理。空白文本直接丢掉。"""
        cleaned = text.strip()
        if not cleaned:
            return SendDecision()
        with self._lock:
            if active_turn_id is None:
                return SendDecision(start_now=cleaned)
            self._pending = cleaned
        return SendDecision(cancel_turn_id=active_turn_id)

    def take_after_turn(self) -> str | None:
        """回合结束后取走待发文本（取走即清空）。"""
        with self._lock:
            text, self._pending = self._pending, None
        return text


@dataclass(frozen=True)
class TurnLatency:
    """一个回合的延迟打点，单位毫秒；没发生的点是 None。"""

    turn_id: str
    first_token_ms: int | None
    first_audio_ms: int | None
    total_ms: int


class LatencyTracker:
    """按回合打点：首字、首音、整轮耗时。

    口径见 docs/product.md 的「成功指标」：首字 = turn.start → 第一个 llm.token，
    首音 = turn.start → 第一个 tts.chunk。时钟可注入，测试里不用 sleep。

    事件可能同时来自回合工作线程和界面线程（渲染进程的回传由定时器轮询），
    所以内部有锁。
    """

    def __init__(self, *, clock: Callable[[], float] = time.monotonic) -> None:
        self._clock = clock
        self._lock = threading.Lock()
        self._started: dict[str, float] = {}
        self._first_token: dict[str, float] = {}
        self._first_audio: dict[str, float] = {}

    def observe(self, event: Event) -> TurnLatency | None:
        """记一条事件。回合结束时返回本轮汇总，其余情况返回 None。"""
        if isinstance(event, TurnStartEvent):
            with self._lock:
                self._started[event.turn_id] = self._clock()
            return None

        if isinstance(event, LlmTokenEvent):
            with self._lock:
                self._first_token.setdefault(event.turn_id, self._clock())
            return None

        if isinstance(event, TtsChunkEvent):
            with self._lock:
                self._first_audio.setdefault(event.turn_id, self._clock())
            return None

        if isinstance(event, TurnDoneEvent | TurnCancelledEvent):
            return self._finish(event.turn_id)

        return None

    def _finish(self, turn_id: str) -> TurnLatency | None:
        """结算一个回合。没打过 start 的（比如启动期错误）返回 None。"""
        now = self._clock()
        with self._lock:
            start = self._started.pop(turn_id, None)
            token = self._first_token.pop(turn_id, None)
            audio = self._first_audio.pop(turn_id, None)
        if start is None:
            return None
        return TurnLatency(
            turn_id=turn_id,
            first_token_ms=None if token is None else _to_ms(token - start),
            first_audio_ms=None if audio is None else _to_ms(audio - start),
            total_ms=_to_ms(now - start),
        )


def _to_ms(seconds: float) -> int:
    """秒 → 毫秒（取整）。"""
    return int(round(seconds * 1000))
