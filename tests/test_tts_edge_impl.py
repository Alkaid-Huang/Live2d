"""tts.edge_impl 的测试：全程使用假通信对象，不联网、不装 edge-tts。"""

from __future__ import annotations

from pathlib import Path
from typing import Any

import pytest

from tts import edge_impl
from tts.base import TtsError, VoiceProfile, edge_profile
from tts.edge_impl import EdgeTtsBackend


class FakeCommunicate:
    """替身：记录参数，按预设写文件、抛错或触发回调。"""

    def __init__(
        self,
        text: str,
        voice: str,
        *,
        rate: str,
        write_bytes: bytes | None,
        error: Exception | None = None,
        on_save: Any = None,
    ) -> None:
        self.text = text
        self.voice = voice
        self.rate = rate
        self._write_bytes = write_bytes
        self._error = error
        self._on_save = on_save
        self.saved_paths: list[str] = []

    async def save(self, path: str) -> None:
        self.saved_paths.append(path)
        if self._on_save is not None:
            self._on_save(path)
        if self._error is not None:
            raise self._error
        if self._write_bytes is not None:
            Path(path).write_bytes(self._write_bytes)


def _recording_factory(
    *,
    write_bytes: bytes | None = b"mp3-bytes",
    error: Exception | None = None,
    on_save: Any = None,
) -> tuple[Any, list[FakeCommunicate]]:
    """返回一个工厂和它创建过的替身列表，便于断言调用参数。"""
    instances: list[FakeCommunicate] = []

    def _build(text: str, voice: str, *, rate: str) -> FakeCommunicate:
        instance = FakeCommunicate(
            text,
            voice,
            rate=rate,
            write_bytes=write_bytes,
            error=error,
            on_save=on_save,
        )
        instances.append(instance)
        return instance

    return _build, instances


@pytest.fixture
def install_factory(monkeypatch: pytest.MonkeyPatch) -> Any:
    def _install(factory: Any) -> None:
        monkeypatch.setattr(edge_impl, "_communicate_factory", factory)

    return _install


def test_synthesize_writes_file_and_yields_chunk(
    tmp_path: Path, install_factory: Any
) -> None:
    factory, instances = _recording_factory()
    install_factory(factory)

    backend = EdgeTtsBackend(audio_dir=tmp_path)
    chunks = list(
        backend.synthesize(
            "你好",
            edge_profile("zh-CN-XiaoxiaoNeural", rate="+10%"),
            turn_id="turn-1",
            segment_index=2,
            segment_total=5,
        )
    )

    assert len(chunks) == 1
    chunk = chunks[0]
    assert chunk.path.name == "turn-1-2.mp3"
    assert chunk.path.read_bytes() == b"mp3-bytes"
    assert chunk.format == "mp3"
    assert chunk.segment_index == 2
    assert chunk.segment_total == 5

    assert len(instances) == 1
    assert instances[0].text == "你好"
    assert instances[0].voice == "zh-CN-XiaoxiaoNeural"
    assert instances[0].rate == "+10%"


def test_empty_text_produces_nothing(tmp_path: Path, install_factory: Any) -> None:
    install_factory(_recording_factory()[0])
    backend = EdgeTtsBackend(audio_dir=tmp_path / "nested")

    chunks = list(
        backend.synthesize(
            "   ",
            edge_profile("v"),
            turn_id="turn-1",
            segment_index=0,
            segment_total=1,
        )
    )

    assert chunks == []
    assert not (tmp_path / "nested").exists()


def test_cancel_before_synthesis(tmp_path: Path, install_factory: Any) -> None:
    install_factory(_recording_factory()[0])
    backend = EdgeTtsBackend(audio_dir=tmp_path)
    backend.cancel("turn-1")

    chunks = list(
        backend.synthesize(
            "你好",
            edge_profile("v"),
            turn_id="turn-1",
            segment_index=0,
            segment_total=1,
        )
    )

    assert chunks == []
    assert list(tmp_path.iterdir()) == []


def test_cancel_during_synthesis_removes_partial_file(
    tmp_path: Path, install_factory: Any
) -> None:
    backend = EdgeTtsBackend(audio_dir=tmp_path)

    def _cancel_midway(path: str) -> None:
        backend.cancel("turn-1")

    install_factory(_recording_factory(on_save=_cancel_midway)[0])

    chunks = list(
        backend.synthesize(
            "你好",
            edge_profile("v"),
            turn_id="turn-1",
            segment_index=0,
            segment_total=1,
        )
    )

    assert chunks == []
    assert list(tmp_path.iterdir()) == []


def test_network_error_is_translated_and_partial_removed(
    tmp_path: Path, install_factory: Any
) -> None:
    def _write_partial(path: str) -> None:
        Path(path).write_bytes(b"partial")

    install_factory(
        _recording_factory(error=RuntimeError("connection reset"), on_save=_write_partial)[0]
    )
    backend = EdgeTtsBackend(audio_dir=tmp_path)

    with pytest.raises(TtsError) as excinfo:
        list(
            backend.synthesize(
                "你好",
                edge_profile("v"),
                turn_id="turn-1",
                segment_index=0,
                segment_total=1,
            )
        )

    assert excinfo.value.code == "tts_error"
    assert "失败" in str(excinfo.value)
    assert list(tmp_path.iterdir()) == []


def test_timeout_is_translated(tmp_path: Path, install_factory: Any) -> None:
    install_factory(_recording_factory(error=TimeoutError())[0])
    backend = EdgeTtsBackend(audio_dir=tmp_path)

    with pytest.raises(TtsError, match="超时"):
        list(
            backend.synthesize(
                "你好",
                edge_profile("v"),
                turn_id="turn-1",
                segment_index=0,
                segment_total=1,
            )
        )


def test_missing_voice_raises_before_calling_backend(
    tmp_path: Path, install_factory: Any
) -> None:
    factory, instances = _recording_factory()
    install_factory(factory)
    backend = EdgeTtsBackend(audio_dir=tmp_path)

    with pytest.raises(TtsError, match="voice"):
        list(
            backend.synthesize(
                "你好",
                VoiceProfile(backend="edge", params={}),
                turn_id="turn-1",
                segment_index=0,
                segment_total=1,
            )
        )

    assert instances == []


def test_no_file_produced_is_an_error(tmp_path: Path, install_factory: Any) -> None:
    install_factory(_recording_factory(write_bytes=None)[0])
    backend = EdgeTtsBackend(audio_dir=tmp_path)

    with pytest.raises(TtsError, match="没有产出文件"):
        list(
            backend.synthesize(
                "你好",
                edge_profile("v"),
                turn_id="turn-1",
                segment_index=0,
                segment_total=1,
            )
        )
