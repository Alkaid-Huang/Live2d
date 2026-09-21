"""回合编排：一次用户输入怎么走完 LLM → 情感 → TTS 的全程。

职责边界见 docs/contracts.md 第 1 节：

- runtime 决定"什么时候调 LLM、什么时候调 TTS、什么时候取消"
- runtime 不认识队列、不认识 Qt、不认识 edge_tts：事件通过 sink 回调出去，
  语音后端由外部注入
- runtime 不自建线程。``send()`` 是阻塞的，调用方（界面层）自己把它放进后台线程，
  这样线程的创建和收尾都留在调用方，runtime 不需要去 join 别人管理的线程

调用约定：**同一时刻只允许一个回合在跑**。要打断当前回合，先调 ``cancel()``，
等 ``send()`` 返回之后再开下一个。

两处由契约推出来的行为，写在这里免得后面被当成 bug：

- 中途取消时，**已经生成一半的回复不进历史**（只有完整回复才入历史），
  但用户那条消息保留——它确实发出去了
- 出错时按契约第 3 节用 ``turn.cancelled(reason="error")`` 收尾，不用 turn.done
"""

from __future__ import annotations

import logging
import threading
import uuid
from dataclasses import dataclass, field
from typing import Protocol

from config import Settings
from emotion import detect
from events import (
    CancelReason,
    EmotionDetectedEvent,
    ErrorEvent,
    Event,
    EventSink,
    LlmDoneEvent,
    LlmTokenEvent,
    TtsChunkEvent,
    TtsStateEvent,
    TurnCancelledEvent,
    TurnDoneEvent,
    TurnStartEvent,
)
from llm import stream_reply
from llm.schemas import LLMError, Message
from tts import TtsBackend, TtsChunk, TtsError, VoiceProfile, split_sentences

logger = logging.getLogger(__name__)

#: M1 的 system prompt。角色设定在 M2 做成可配置，M1 先写死一句。
DEFAULT_SYSTEM_PROMPT = (
    "你是一个友好的数字角色。用简短、自然的口语回答，一次不要超过三句话。"
)

#: emotion.detected 事件的来源标记。M2 换成分类模型后会有别的取值。
EMOTION_SOURCE = "rules"

__all__ = ["DEFAULT_SYSTEM_PROMPT", "EMOTION_SOURCE", "ChatRuntime", "RendererControl"]


class _TurnCancelled(Exception):
    """内部控制流：回合被取消，直接展开到 send() 统一收尾。"""


class _ConfigError(Exception):
    """配置不完整（比如没填 API Key）。对应错误码 invalid_request。

    它与 llm_error 的区别在于：这个错误用户能照着改，不需要重试。
    """

    code = "invalid_request"


class RendererControl(Protocol):
    """runtime 眼里的"呈现通道"：把声音和表情送到看得见的地方。

    桌面形态的实现是 stage/channel.py（往渲染子进程的队列里发命令）；将来的
    Web 形态实现成"往 WebSocket 发帧"。runtime 只依赖这三个方法，既不认识队列，
    也不认识 pygame，所以核心层不用 import 任何 GUI 或渲染库。
    """

    def play(
        self,
        *,
        turn_id: str,
        segment_index: int,
        segment_total: int,
        path: str,
        format: str,
    ) -> None:
        """播一段音频。"""
        ...

    def set_emotion(self, *, turn_id: str, label: str) -> None:
        """按情感换表情与动作。"""
        ...

    def stop(self, turn_id: str) -> None:
        """立刻停止播放、口型归位。"""
        ...


@dataclass
class _Turn:
    """一个回合的可变状态。只在 runtime 内部流转。"""

    turn_id: str
    cancel_flag: threading.Event = field(default_factory=threading.Event)
    reason: CancelReason = "user_stop"


class ChatRuntime:
    """一个会话的编排器。一个实例管一个会话。"""

    def __init__(
        self,
        *,
        sink: EventSink,
        tts_backend: TtsBackend,
        settings: Settings,
        voice: VoiceProfile,
        system_prompt: str = DEFAULT_SYSTEM_PROMPT,
        session_id: str | None = None,
        renderer: RendererControl | None = None,
    ) -> None:
        self.session_id = session_id or uuid.uuid4().hex
        self._sink = sink
        self._tts = tts_backend
        self._settings = settings
        self._voice = voice
        # renderer 允许是 None：单元测试和"只关心文本"的用法都不需要它。
        self._renderer = renderer
        self._messages: list[Message] = [Message(role="system", content=system_prompt)]
        self._lock = threading.Lock()
        self._active: _Turn | None = None

    # ------------------------------------------------------------------ #
    # 对外接口
    # ------------------------------------------------------------------ #

    @property
    def history(self) -> tuple[Message, ...]:
        """当前会话的全部消息（含 system）。M1 只存在内存里。"""
        return tuple(self._messages)

    @property
    def active_turn_id(self) -> str | None:
        """正在跑的回合 id；没有就是 None。界面用它决定要不要发取消。"""
        with self._lock:
            return self._active.turn_id if self._active is not None else None

    def cancel(self, turn_id: str, reason: CancelReason = "user_stop") -> bool:
        """请求取消某个回合。

        只设标志，不阻塞：``send()`` 会在下一个检查点（收到一段 LLM 增量之前、
        交付一个音频分片之前、开始合成下一句之前）看到标志并收尾。

        同时通知语音后端，让它也在产出下一片之前停下——网络请求可能正卡在中间。

        Returns:
            bool: 是否确实取消了正在跑的那个回合（id 对不上或没有回合时返回 False）。
        """
        with self._lock:
            active = self._active
            if active is None or active.turn_id != turn_id:
                return False
            active.reason = reason
            active.cancel_flag.set()
        self._tts.cancel(turn_id)
        self._stop_playback(turn_id)
        return True

    def send(self, user_text: str) -> str:
        """跑完一整个回合，阻塞到结束。返回 turn_id。

        Raises:
            ValueError: 消息是空的。
            RuntimeError: 上一个回合还没结束（调用方必须先 cancel 并等它返回）。
        """
        text = user_text.strip()
        if not text:
            raise ValueError("消息不能为空")

        with self._lock:
            if self._active is not None:
                raise RuntimeError(f"上一个回合还没结束：{self._active.turn_id}")
            turn = _Turn(turn_id=uuid.uuid4().hex)
            self._active = turn

        try:
            self._emit(TurnStartEvent(turn_id=turn.turn_id, user_text=text))
            self._messages.append(Message(role="user", content=text))
            self._run_turn(turn)
        except _TurnCancelled:
            self._emit(TurnCancelledEvent(turn_id=turn.turn_id, reason=turn.reason))
        except TtsError as exc:
            # 先报状态再报错误：界面要能区分"语音失败了"和"模型挂了"。
            self._emit(TtsStateEvent(turn_id=turn.turn_id, state="failed", detail=str(exc)))
            self._fail(turn, exc.code, str(exc))
        except LLMError as exc:
            self._fail(turn, exc.code, str(exc))
        except _ConfigError as exc:
            self._fail(turn, exc.code, str(exc))
        except Exception as exc:  # 兜底：不让异常从 worker 线程里静默消失
            logger.exception("回合执行失败")
            self._fail(turn, "internal_error", f"{type(exc).__name__}: {exc}")
        else:
            self._emit(TurnDoneEvent(turn_id=turn.turn_id))
        finally:
            with self._lock:
                if self._active is turn:
                    self._active = None

        return turn.turn_id

    # ------------------------------------------------------------------ #
    # 回合内部
    # ------------------------------------------------------------------ #

    def _run_turn(self, turn: _Turn) -> None:
        """一个回合的正片：LLM → 情感 → TTS。全程可能在任何检查点抛出取消。"""
        reply, finish_reason = self._stream_reply(turn)
        self._emit(LlmDoneEvent(turn_id=turn.turn_id, finish_reason=finish_reason))
        # 到这里回复已经完整了，可以进历史。中途取消的半个回复不会走到这里。
        self._messages.append(Message(role="assistant", content=reply))

        label = detect(reply)
        self._emit(
            EmotionDetectedEvent(
                turn_id=turn.turn_id,
                label=str(label.value),
                source=EMOTION_SOURCE,
            )
        )
        self._show_emotion(turn, str(label.value))

        self._speak(turn, reply)

    def _stream_reply(self, turn: _Turn) -> tuple[str, str]:
        """把 LLM 的增量逐段推给界面，返回完整回复和结束原因。"""
        settings = self._settings
        try:
            settings.require_llm_credentials()
        except RuntimeError as exc:
            # 缺 Key 是配置问题，不是 Provider 问题：用户照着改就行，不用重试。
            raise _ConfigError(str(exc)) from exc

        parts: list[str] = []
        for delta in stream_reply(
            list(self._messages),
            settings.llm_model,
            provider=settings.llm_provider,
            api_key=settings.llm_api_key or None,
            base_url=settings.llm_base_url or None,
            temperature=settings.llm_temperature,
        ):
            self._check(turn)
            parts.append(delta)
            self._emit(LlmTokenEvent(turn_id=turn.turn_id, text=delta))
        self._check(turn)
        # router 只产出文本，没有把 Provider 的结束原因带上来（见 LlmDoneEvent 的说明）。
        return "".join(parts), "stop"

    def _speak(self, turn: _Turn, reply: str) -> None:
        """按句合成语音，逐片交给渲染进程。

        句子由 runtime 切（tts 层的 split_sentences），序号也由 runtime 给：
        序号是切句者的信息，不是后端的信息（docs/contracts.md 第 4 节）。
        """
        sentences = split_sentences(reply)
        if not sentences:
            return

        self._emit(TtsStateEvent(turn_id=turn.turn_id, state="synthesizing"))
        total = len(sentences)
        for index, sentence in enumerate(sentences):
            self._check(turn)
            chunks = self._tts.synthesize(
                sentence,
                self._voice,
                turn_id=turn.turn_id,
                segment_index=index,
                segment_total=total,
            )
            for chunk in chunks:
                # 取消时连刚合成好、还没交付的这一片也丢掉：后端已经按契约
                # 停在下一次产出之前，剩下的活不用再干。
                self._check(turn)
                self._emit(
                    TtsChunkEvent(
                        turn_id=turn.turn_id,
                        segment_index=chunk.segment_index,
                        segment_total=chunk.segment_total,
                        path=str(chunk.path),
                        format=chunk.format,
                    )
                )
                self._play(chunk, turn)

    # ------------------------------------------------------------------ #
    # 小工具
    # ------------------------------------------------------------------ #

    def _emit(self, event: Event) -> None:
        self._sink(event)

    def _check(self, turn: _Turn) -> None:
        """取消检查点。契约要求 turn.cancelled 之后不再有任何该回合的事件。"""
        if turn.cancel_flag.is_set():
            raise _TurnCancelled

    def _fail(self, turn: _Turn, code: str, message: str) -> None:
        """错误收尾：先报错，再按契约第 3 节以 turn.cancelled(reason="error") 终止。"""
        self._stop_playback(turn.turn_id)
        self._emit(ErrorEvent(turn_id=turn.turn_id, code=code, message=message))
        self._emit(TurnCancelledEvent(turn_id=turn.turn_id, reason="error"))

    # ------------------------------------------------------------------ #
    # 呈现通道（没有渲染进程时全部是空操作）
    # ------------------------------------------------------------------ #

    def _play(self, chunk: TtsChunk, turn: _Turn) -> None:
        if self._renderer is None:
            return
        self._renderer.play(
            turn_id=turn.turn_id,
            segment_index=chunk.segment_index,
            segment_total=chunk.segment_total,
            path=str(chunk.path),
            format=chunk.format,
        )

    def _show_emotion(self, turn: _Turn, label: str) -> None:
        if self._renderer is None:
            return
        self._renderer.set_emotion(turn_id=turn.turn_id, label=label)

    def _stop_playback(self, turn_id: str) -> None:
        """停播放。取消和出错都要走这里，否则取消之后旧语音还会响完。"""
        if self._renderer is None:
            return
        self._renderer.stop(turn_id)
