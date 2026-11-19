"""音频相关的契约类型：TTS 产出什么、音色怎么描述。"""

from __future__ import annotations

from collections.abc import Mapping
from dataclasses import dataclass
from pathlib import Path


@dataclass(frozen=True, slots=True)
class TtsChunk:
    """一段已经落盘的音频。

    Attributes:
        path: 音频文件路径。
        format: 音频格式，目前恒为 ``"mp3"``。
        segment_index: 本片序号，从 0 开始。
        segment_total: 本回合总片数，大于 0。

    Note:
        没有 ``duration_ms``：目前没有消费者，且 edge 与本地模型无法以同等代价提供它。

    Example:
        ```python
        chunk = TtsChunk(path=Path("tmp_audio/a-0.mp3"), format="mp3",
                         segment_index=0, segment_total=2)
        chunk.path.is_file()
        ```
    """

    path: Path
    format: str
    segment_index: int
    segment_total: int


@dataclass(frozen=True, slots=True)
class VoiceProfile:
    """"用什么音色说话"的配置对象。

    后端专属参数留在 ``params`` 里，不拍平成公共字段。

    Attributes:
        backend: 后端名，目前只有 ``"edge"``。
        params: 该后端的专属参数。edge 用 ``voice`` 与 ``rate``。

    Example:
        ```python
        VoiceProfile(backend="edge", params={"voice": "zh-CN-XiaoxiaoNeural", "rate": "+0%"})
        ```
    """

    backend: str
    params: Mapping[str, str]
