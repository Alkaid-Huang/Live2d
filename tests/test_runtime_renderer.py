"""runtime 与呈现通道的接线：音频与情感有没有送到渲染进程、取消有没有停播。"""

from __future__ import annotations

import os
from collections.abc import Callable, Iterator, Sequence
from pathlib import Path
from typing import Any

import pytest

import runtime as runtime_module
from config import Settings
from events import Event
from runtime import ChatRuntime
from tts import TtsChunk, edge_profile


@pytest.fixture(autouse=True)
def _isolate_environment(monkeypatch: pytest.MonkeyPatch) -> None:
    for key in list(os.environ):
        upper = key.upper()
        if upper == "LOG_LEVEL" or upper.startswith(("LLM_", "TTS_", "LIVE2D_")):
            monkeypatch.delenv(key, raising=False)


class RecordingRenderer:
    """假呈现通道：只记录调用顺序。"""

    def __init__(self) -> None:
        self.played: list[tuple[str, int, str]] = []
        self.emotions: list[tuple[str, str]] = []
        self.stopped: list[str] = []
        #: 每个动作发生时打的标记，用来断言"情感先于音频"这类顺序。
        self.order: list[str] = []

    def play(
        self,
        *,
        turn_id: str,
        segment_index: int,
        segment_total: int,
        path: str,
        format: str,
    ) -> None:
        self.played.append((turn_id, segment_index, format))
        self.order.append("play")

    def set_emotion(self, *, turn_id: str, label: str) -> None:
        self.emotions.append((turn_id, label))
        self.order.append("emotion")

    def stop(self, turn_id: str) -> None:
        self.stopped.append(turn_id)
        self.order.append("stop")


class FakeTts:
    """假语音后端：落一个真文件，不联网。"""

    def __init__(self, audio_dir: Path) -> None:
        self.audio_dir = audio_dir
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
        return None


def install_stream(
    monkeypatch: pytest.MonkeyPatch,
    deltas: Sequence[str],
    error: Exception | None = None,
) -> None:
    def stream(messages: Any, model: str, **kwargs: Any) -> Iterator[str]:
        yield from deltas
        if error is not None:
            raise error

    monkeypatch.setattr(runtime_module, "stream_reply", stream)


def make_runtime(
    tmp_path: Path,
) -> tuple[ChatRuntime, list[Event], RecordingRenderer, FakeTts]:
    events: list[Event] = []
    renderer = RecordingRenderer()
    tts = FakeTts(tmp_path)
    settings = Settings(_env_file=None, llm_api_key="sk-test-not-a-real-key")
    chat = ChatRuntime(
        sink=events.append,
        tts_backend=tts,
        settings=settings,
        voice=edge_profile("zh-CN-XiaoxiaoNeural"),
        session_id="s1",
        renderer=renderer,
    )
    return chat, events, renderer, tts


def test_each_chunk_is_handed_to_the_renderer(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    chat, _, renderer, _ = make_runtime(tmp_path)
    install_stream(monkeypatch, ["你好。", "今天天气不错。"])

    chat.send("在吗")

    assert [segment for _, segment, _ in renderer.played] == [0, 1]
    assert all(fmt == "mp3" for _, _, fmt in renderer.played)


def test_emotion_is_shown_before_the_audio(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    chat, _, renderer, _ = make_runtime(tmp_path)
    install_stream(monkeypatch, ["今天真开心！"])

    chat.send("你好")

    assert renderer.order[0] == "emotion"
    assert renderer.emotions[0][1] == "开心"


def test_cancel_stops_playback(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    chat, _, renderer, tts = make_runtime(tmp_path)

    def cancel_mid_turn(turn_id: str) -> None:
        """第一段音频交付之后立刻取消，模拟"播到一半用户又发了一条"。"""
        chat.cancel(turn_id, reason="user_new_message")

    tts.on_chunk = cancel_mid_turn
    install_stream(monkeypatch, ["第一句。", "第二句。"])
    chat.send("你好")

    assert len(renderer.stopped) == 1
    assert renderer.played[0][0] == renderer.stopped[0]


def test_cancel_by_the_user_also_stops_playback(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    chat, _, renderer, _ = make_runtime(tmp_path)

    def cancel_from_another_thread() -> None:
        active = chat.active_turn_id
        assert active is not None
        assert chat.cancel(active, reason="user_new_message") is True

    # 第一段交付之后立刻取消，模拟"用户又发了一条"。
    monkeypatch.setattr(
        runtime_module,
        "stream_reply",
        lambda messages, model, **kwargs: iter(_cancelling_stream(cancel_from_another_thread)),
    )

    chat.send("你好")

    assert renderer.stopped != []


def _cancelling_stream(on_first: Callable[[], None]) -> Iterator[str]:
    yield "第一"
    on_first()
    yield "二"


def test_error_also_stops_playback(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    from llm.schemas import LLMTimeoutError

    chat, events, renderer, _ = make_runtime(tmp_path)
    install_stream(monkeypatch, [], error=LLMTimeoutError("超时"))

    chat.send("你好")

    assert renderer.stopped != []
    assert [event.type for event in events][-1] == "turn.cancelled"
