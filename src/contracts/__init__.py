"""契约包：端口、事件、数据类型、异常。

这是唯一允许被"任何层"import 的模块；反过来它只 import 标准库。
实现层（``llm`` / ``tts`` / ``stage`` / ``ui`` / ``runtime``）都依赖这里，
依赖方向永远指向本包。

Example:
    ```python
    from contracts import Event, LlmTokenEvent, RendererControl, TtsBackend

    event = LlmTokenEvent(turn_id="9f3c", text="你")
    assert isinstance(event, Event)
    ```
"""

from __future__ import annotations

from contracts.audio import TtsChunk, VoiceProfile
from contracts.errors import LLMError, LLMProviderError, LLMTimeoutError, TtsError
from contracts.events import (
    CancelReason,
    EmotionDetectedEvent,
    ErrorEvent,
    Event,
    EventSink,
    LlmDoneEvent,
    LlmTokenEvent,
    TtsChunkEvent,
    TtsState,
    TtsStateEvent,
    TurnCancelledEvent,
    TurnDoneEvent,
    TurnStartEvent,
)
from contracts.messages import Message, Role
from contracts.ports import LlmClient, QueueLike, RendererControl, TtsBackend

__all__ = [
    "LLMError",
    "LLMProviderError",
    "LLMTimeoutError",
    "CancelReason",
    "EmotionDetectedEvent",
    "ErrorEvent",
    "Event",
    "EventSink",
    "LlmClient",
    "LlmDoneEvent",
    "LlmTokenEvent",
    "Message",
    "QueueLike",
    "RendererControl",
    "Role",
    "TtsBackend",
    "TtsChunk",
    "TtsChunkEvent",
    "TtsError",
    "TtsState",
    "TtsStateEvent",
    "TurnCancelledEvent",
    "TurnDoneEvent",
    "TurnStartEvent",
    "VoiceProfile",
]
