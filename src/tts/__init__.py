"""TTS 层。对外只暴露抽象与装配入口，不暴露任何具体后端。"""

from __future__ import annotations

from pathlib import Path

from tts.base import (
    TtsBackend,
    TtsChunk,
    TtsError,
    TtsState,
    VoiceProfile,
    edge_profile,
    split_sentences,
)

__all__ = [
    "TtsBackend",
    "TtsChunk",
    "TtsError",
    "TtsState",
    "VoiceProfile",
    "create_tts_backend",
    "edge_profile",
    "split_sentences",
]


def create_tts_backend(backend: str, *, audio_dir: Path) -> TtsBackend:
    """按名字装配一个语音后端。全系统唯一知道具体后端的地方。

    Args:
        backend: 后端名，目前只接受 ``"edge"``。
        audio_dir: 音频落盘目录，不存在时由后端自己创建。

    Returns:
        满足 ``contracts.TtsBackend`` 的后端实例。

    Raises:
        ValueError: 后端名不在支持列表里。

    Example:
        ```python
        backend = create_tts_backend("edge", audio_dir=Path("tmp_audio"))
        backend.cancel("9f3c")
        ```
    """
    if backend == "edge":
        from tts.edge_impl import EdgeTtsBackend

        return EdgeTtsBackend(audio_dir=audio_dir)
    raise ValueError(f"未知的 TTS 后端：{backend}")
