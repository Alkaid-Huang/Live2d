"""runtime 的测试。

全程不联网：LLM 用假的流替代（monkeypatch 掉 runtime 模块里的名字），
TTS 用假后端。测试之间不共享状态。
"""

from __future__ import annotations

import os
from collections.abc import Callable, Iterator, Sequence
from pathlib import Path
from typing import Any

import pytest

import runtime as runtime_module
from config import Settings
from contracts import Event, LLMTimeoutError
from llm import router as llm_router
from runtime import ChatRuntime
from tts import TtsChunk, TtsError, edge_profile

InstallStream = Callable[..., None]


@pytest.fixture(autouse=True)
def _isolate_environment(monkeypatch: pytest.MonkeyPatch) -> None:
    """清掉外部环境里的同名变量，保证结果只由代码决定（同 test_config.py）。"""
    for key in list(os.environ):
        upper = key.upper()
        if upper == "LOG_LEVEL" or upper.startswith(("LLM_", "TTS_", "LIVE2D_")):
            monkeypatch.delenv(key, raising=False)


def make_stream(
    deltas: Sequence[str],
    *,
    after_first_delta: Callable[[], None] | None = None,
    error: Exception | None = None,
) -> Callable[..., Iterator[str]]:
    """造一个假的 stream_reply。

    ``after_first_delta`` 在第一段交付之后触发，用来模拟"回复到一半用户插话"；
    ``error`` 让流在第一段之后抛错。
    """

    def stream(messages: Any, model: str, **kwargs: Any) -> Iterator[str]:
        for index, delta in enumerate(deltas):
            yield delta
            if index == 0:
                if after_first_delta is not None:
                    after_first_delta()
                if error is not None:
                    raise error

    return stream


@pytest.fixture
def use_stream(monkeypatch: pytest.MonkeyPatch) -> InstallStream:
    """把 runtime 模块里的 stream_reply 换掉。测试结束后自动还原。"""

    def install(
        deltas: Sequence[str],
        *,
        after_first_delta: Callable[[], None] | None = None,
        error: Exception | None = None,
    ) -> None:
        monkeypatch.setattr(
            llm_router,
            "stream_reply",
            make_stream(deltas, after_first_delta=after_first_delta, error=error),
        )

    return install


class FakeTts:
    """假语音后端：产出真实存在的小文件，记录调用，不联网。"""

    def __init__(self, audio_dir: Path, *, fail_at_index: int | None = None) -> None:
        self.audio_dir = audio_dir
        self.cancelled: list[str] = []
        #: 真正被送去合成的句子：(句子, 序号)
        self.calls: list[tuple[str, int]] = []
        self.fail_at_index = fail_at_index
        #: 每个分片交付之后调用一次：模拟"播到一半用户打断"。
        self.on_chunk: Callable[[str], None] | None = None

    def synthesize(
        self,
        text: str,
        voice: Any,
        *,
        turn_id: str,
        segment_index: int,
        segment_total: int,
    ) -> Iterator[TtsChunk]:
        self.calls.append((text, segment_index))
        if self.fail_at_index is not None and segment_index >= self.fail_at_index:
            raise TtsError("合成失败")
        path = self.audio_dir / f"{turn_id}-{segment_index}.mp3"
        path.write_bytes(b"fake-audio")
        yield TtsChunk(
            path=path,
            format="mp3",
            segment_index=segment_index,
            segment_total=segment_total,
        )
        if self.on_chunk is not None:
            self.on_chunk(turn_id)

    def cancel(self, turn_id: str) -> None:
        self.cancelled.append(turn_id)


def make_runtime(
    tmp_path: Path,
    *,
    tts: FakeTts | None = None,
    api_key: str = "sk-test-not-a-real-key",
) -> tuple[ChatRuntime, list[Event], FakeTts]:
    events: list[Event] = []
    backend = tts if tts is not None else FakeTts(tmp_path)
    settings = Settings(_env_file=None, llm_api_key=api_key)
    chat = ChatRuntime(
        sink=events.append,
        tts_backend=backend,
        settings=settings,
        voice=edge_profile("zh-CN-XiaoxiaoNeural"),
        session_id="s1",
    )
    return chat, events, backend


def types_of(events: Sequence[Event]) -> list[str]:
    return [event.type for event in events]


def test_normal_turn_event_order(tmp_path: Path, use_stream: InstallStream) -> None:
    chat, events, _ = make_runtime(tmp_path)
    use_stream(["你好。", "今天天气不错。"])

    chat.send("在吗")

    assert types_of(events) == [
        "turn.start",
        "llm.token",
        "llm.token",
        "llm.done",
        "emotion.detected",
        "tts.state",
        "tts.chunk",
        "tts.chunk",
        "turn.done",
    ]


def test_all_events_share_one_turn_id(tmp_path: Path, use_stream: InstallStream) -> None:
    chat, events, _ = make_runtime(tmp_path)
    use_stream(["好的。"])

    returned = chat.send("你好")

    assert {event.turn_id for event in events} == {returned}
    assert events[0].to_frame()["turn_id"] == returned


def test_reply_is_split_into_numbered_chunks(
    tmp_path: Path,
    use_stream: InstallStream,
) -> None:
    chat, events, backend = make_runtime(tmp_path)
    use_stream(["第一句。", "第二句。", "第三句。"])

    chat.send("说吧")

    assert [call[0] for call in backend.calls] == ["第一句。", "第二句。", "第三句。"]
    chunks = [event for event in events if event.type == "tts.chunk"]
    assert [chunk.to_frame()["data"]["segment_total"] for chunk in chunks] == [3, 3, 3]
    assert [chunk.to_frame()["data"]["segment_index"] for chunk in chunks] == [0, 1, 2]


def test_synthesizing_state_is_announced(tmp_path: Path, use_stream: InstallStream) -> None:
    """界面从第一天就要能显示"合成中"（docs/contracts.md 第 2 节）。"""
    chat, events, _ = make_runtime(tmp_path)
    use_stream(["你好。"])

    chat.send("在吗")

    states = [event.to_frame()["data"]["state"] for event in events if event.type == "tts.state"]
    assert states == ["synthesizing"]


def test_empty_reply_produces_no_audio_events(tmp_path: Path, use_stream: InstallStream) -> None:
    chat, events, backend = make_runtime(tmp_path)
    use_stream([])

    chat.send("在吗")

    assert types_of(events) == ["turn.start", "llm.done", "emotion.detected", "turn.done"]
    assert backend.calls == []


def test_emotion_label_comes_from_the_rules(tmp_path: Path, use_stream: InstallStream) -> None:
    chat, events, _ = make_runtime(tmp_path)
    use_stream(["哈哈哈哈，太好了。"])

    chat.send("讲个笑话")

    emotion = next(event for event in events if event.type == "emotion.detected")
    assert emotion.to_frame()["data"] == {"label": "开心", "source": "rules"}


def test_unmapped_emotion_is_passed_through_as_is(
    tmp_path: Path,
    use_stream: InstallStream,
) -> None:
    """runtime 只发标签，不替渲染进程决定动作组（docs/contracts.md 第 4 节）。"""
    chat, events, _ = make_runtime(tmp_path)
    use_stream(["竟然是这样。"])

    chat.send("你知道吗")

    emotion = next(event for event in events if event.type == "emotion.detected")
    assert emotion.to_frame()["data"]["label"] == "惊讶"


def test_cancel_during_reply_stops_remaining_tokens(
    tmp_path: Path,
    use_stream: InstallStream,
) -> None:
    chat, events, _ = make_runtime(tmp_path)
    use_stream(
        ["前半句。", "后半句。"],
        after_first_delta=lambda: chat.cancel(chat.active_turn_id or "", "user_new_message"),
    )

    chat.send("你好")

    assert types_of(events) == ["turn.start", "llm.token", "turn.cancelled"]
    assert events[-1].to_frame()["data"]["reason"] == "user_new_message"


def test_cancel_during_audio_drops_the_undelivered_chunk(
    tmp_path: Path,
    use_stream: InstallStream,
) -> None:
    fake = FakeTts(tmp_path)
    chat, events, backend = make_runtime(tmp_path, tts=fake)
    use_stream(["第一句。第二句。第三句。"])
    fake.on_chunk = lambda turn_id: chat.cancel(turn_id, "user_stop")

    chat.send("说吧")

    assert types_of(events) == [
        "turn.start",
        "llm.token",
        "llm.done",
        "emotion.detected",
        "tts.state",
        "tts.chunk",
        "turn.cancelled",
    ]
    # 只合成了一句：取消之后剩下的句子不该再送去合成
    assert [call[1] for call in backend.calls] == [0]
    # 并且通知了后端，让卡在中间的请求停下
    assert backend.cancelled == [events[0].turn_id]


def test_cancel_request_for_unknown_turn_is_ignored(tmp_path: Path) -> None:
    chat, _, backend = make_runtime(tmp_path)

    assert chat.cancel("not-a-turn") is False
    assert backend.cancelled == []


def test_partial_reply_does_not_enter_history(
    tmp_path: Path,
    use_stream: InstallStream,
) -> None:
    chat, _, _ = make_runtime(tmp_path)
    use_stream(
        ["前半句。", "后半句。"],
        after_first_delta=lambda: chat.cancel(chat.active_turn_id or "", "user_stop"),
    )

    chat.send("你好")

    assert [(message.role, message.content) for message in chat.history] == [
        ("system", runtime_module.DEFAULT_SYSTEM_PROMPT),
        ("user", "你好"),
    ]


def test_complete_reply_enters_history(tmp_path: Path, use_stream: InstallStream) -> None:
    chat, _, _ = make_runtime(tmp_path)
    use_stream(["你好。"])

    chat.send("在吗")

    assert [message.role for message in chat.history] == ["system", "user", "assistant"]
    assert chat.history[-1].content == "你好。"


def test_next_turn_can_start_after_cancel(tmp_path: Path, use_stream: InstallStream) -> None:
    chat, _, _ = make_runtime(tmp_path)
    use_stream(
        ["前半句。", "后半句。"],
        after_first_delta=lambda: chat.cancel(chat.active_turn_id or "", "user_new_message"),
    )
    chat.send("第一条")
    assert chat.active_turn_id is None

    use_stream(["好。"])
    chat.send("第二条")

    assert chat.active_turn_id is None
    assert [message.content for message in chat.history] == [
        runtime_module.DEFAULT_SYSTEM_PROMPT,
        "第一条",
        "第二条",
        "好。",
    ]


def test_llm_timeout_becomes_an_error_event(
    tmp_path: Path,
    use_stream: InstallStream,
) -> None:
    chat, events, _ = make_runtime(tmp_path)
    use_stream(["前半句"], error=LLMTimeoutError("超时"))

    chat.send("你好")

    assert types_of(events) == ["turn.start", "llm.token", "error", "turn.cancelled"]
    assert events[-2].to_frame()["data"]["code"] == "llm_timeout"
    assert events[-1].to_frame()["data"]["reason"] == "error"


def test_tts_failure_marks_state_and_reports_error(
    tmp_path: Path,
    use_stream: InstallStream,
) -> None:
    fake = FakeTts(tmp_path, fail_at_index=1)
    chat, events, _ = make_runtime(tmp_path, tts=fake)
    use_stream(["第一句。第二句。"])

    chat.send("说吧")

    assert types_of(events) == [
        "turn.start",
        "llm.token",
        "llm.done",
        "emotion.detected",
        "tts.state",
        "tts.chunk",
        "tts.state",
        "error",
        "turn.cancelled",
    ]
    assert events[-3].to_frame()["data"]["state"] == "failed"
    assert events[-2].to_frame()["data"]["code"] == "tts_error"


def test_missing_api_key_is_reported_as_invalid_request(
    tmp_path: Path,
    use_stream: InstallStream,
) -> None:
    chat, events, _ = make_runtime(tmp_path, api_key="")
    use_stream(["不该走到这里"])

    chat.send("你好")

    # 流一帧都没产出，说明检查发生在调用 LLM 之前
    assert types_of(events) == ["turn.start", "error", "turn.cancelled"]
    assert events[1].to_frame()["data"]["code"] == "invalid_request"
    assert "LLM_API_KEY" in str(events[1].to_frame()["data"]["message"])


def test_empty_message_is_rejected(tmp_path: Path) -> None:
    chat, _, _ = make_runtime(tmp_path)

    with pytest.raises(ValueError):
        chat.send("   ")


def test_second_turn_without_cancel_is_rejected(tmp_path: Path) -> None:
    """并发调用是调用方的错，runtime 直说，而不是把两个回合混在一起。"""
    chat, _, _ = make_runtime(tmp_path)
    # 手工摆出"上一回合还在跑"的状态
    chat._active = runtime_module._Turn(turn_id="t-busy")
    try:
        with pytest.raises(RuntimeError, match="上一个回合"):
            chat.send("插队")
    finally:
        chat._active = None
