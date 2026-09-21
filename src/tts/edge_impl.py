"""edge-tts 适配器：全项目唯一允许 import edge_tts 的文件。

对外不暴露 edge-tts 的任何类型或异常，全部翻译成 ``tts.base.TtsError``。

测试接缝：模块级 ``_communicate_factory`` 引用。测试里把它换成假工厂即可，
不需要装 edge-tts，也不需要联网。真实路径在第一次调用时才延迟导入 edge_tts。
"""

from __future__ import annotations

import asyncio
import contextlib
import threading
from collections.abc import Callable, Iterator
from pathlib import Path
from typing import Any

from tts.base import TtsBackend, TtsChunk, TtsError, VoiceProfile

CommunicateFactory = Callable[..., Any]

#: 测试替换点。生产路径上是 None，第一次真正调用时才去碰 edge_tts。
_communicate_factory: CommunicateFactory | None = None


def _default_communicate(text: str, voice: str, *, rate: str) -> Any:
    import edge_tts

    return edge_tts.Communicate(text, voice, rate=rate)


class EdgeTtsBackend(TtsBackend):
    """把 edge-tts 包装成 TtsBackend。"""

    def __init__(self, *, audio_dir: Path, timeout: float = 20.0) -> None:
        self._audio_dir = Path(audio_dir)
        self._timeout = timeout
        self._cancelled: set[str] = set()
        self._lock = threading.Lock()

    def synthesize(
        self,
        text: str,
        voice: VoiceProfile,
        *,
        turn_id: str,
        segment_index: int,
        segment_total: int,
    ) -> Iterator[TtsChunk]:
        if not text.strip():
            return
        if self._is_cancelled(turn_id):
            return

        voice_id = voice.params.get("voice", "").strip()
        if not voice_id:
            raise TtsError("edge 音色档案缺少 voice 参数")
        rate = voice.params.get("rate", "+0%")

        self._audio_dir.mkdir(parents=True, exist_ok=True)
        out_path = self._audio_dir / f"{turn_id}-{segment_index}.mp3"

        factory = _communicate_factory or _default_communicate
        communicate = factory(text, voice_id, rate=rate)

        try:
            asyncio.run(
                asyncio.wait_for(communicate.save(str(out_path)), timeout=self._timeout)
            )
        except Exception as exc:
            _remove_if_exists(out_path)
            raise _translate_error(exc) from exc

        if self._is_cancelled(turn_id):
            _remove_if_exists(out_path)
            return
        if not out_path.is_file():
            _remove_if_exists(out_path)
            raise TtsError(f"语音合成没有产出文件：{out_path}")

        yield TtsChunk(
            path=out_path,
            format="mp3",
            segment_index=segment_index,
            segment_total=segment_total,
        )

    def cancel(self, turn_id: str) -> None:
        with self._lock:
            self._cancelled.add(turn_id)

    def _is_cancelled(self, turn_id: str) -> bool:
        with self._lock:
            return turn_id in self._cancelled


def _translate_error(exc: Exception) -> TtsError:
    name = type(exc).__name__.lower()
    if "timeout" in name:
        return TtsError(f"语音合成超时：{exc}")
    return TtsError(f"语音合成失败：{exc}")


def _remove_if_exists(path: Path) -> None:
    """尽力清理一个可能不存在的文件。

    清理失败不该掩盖原本的错误，所以这里吞掉 OSError——这只影响磁盘卫生，
    不影响能否继续运行。
    """
    with contextlib.suppress(OSError):
        path.unlink(missing_ok=True)
