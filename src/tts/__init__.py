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
    """根据后端名装配一个 TtsBackend。这是全系统唯一知道具体后端的地方。"""
    if backend == "edge":
        from tts.edge_impl import EdgeTtsBackend

        return EdgeTtsBackend(audio_dir=audio_dir)
    raise ValueError(f"未知的 TTS 后端：{backend}")
