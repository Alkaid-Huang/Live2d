"""TTS 层的抽象：数据结构、协议与纯函数。

这一层不 import 任何语音后端，也不 import 网络库（见 AGENTS.md 硬约束 1）。
runtime 只依赖这里的 ``TtsBackend`` 协议，具体后端由 ``tts/__init__.py`` 里的
``create_tts_backend()`` 装配进来。
"""

from __future__ import annotations

from collections.abc import Iterator, Mapping
from dataclasses import dataclass
from pathlib import Path
from typing import Literal, Protocol

TtsState = Literal["idle", "synthesizing", "playing", "failed"]

#: 中文和通用句末标点，换行也算边界。
_SENTENCE_END = frozenset("。！？!?；;\n")


def _is_sentence_end(text: str, index: int) -> bool:
    """判断某位置是不是句末边界。

    英文句点只有"后面是空白或结尾"时才算边界，且不能夹在数字中间——
    否则 ``3.14``、``2.0`` 这类内容会被切成两半。
    """
    char = text[index]
    if char in _SENTENCE_END:
        return True
    if char != ".":
        return False
    if index > 0 and text[index - 1].isdigit():
        return False
    if index + 1 < len(text) and text[index + 1].isdigit():
        return False
    return index + 1 >= len(text) or text[index + 1].isspace()


@dataclass(frozen=True, slots=True)
class TtsChunk:
    """一段已经落盘的音频。

    ``duration_ms`` 故意不放进来：M1 没有消费者，而且 edge 与本地模型无法以
    同等代价提供它（见 ADR 0001 与 docs/contracts.md 第 4 节）。
    """

    path: Path
    format: str
    segment_index: int
    segment_total: int


@dataclass(frozen=True, slots=True)
class VoiceProfile:
    """描述"用什么音色说话"。

    后端专属参数待在 ``params`` 里，不拍平成公共字段。
    """

    backend: str
    params: Mapping[str, str]


def edge_profile(voice: str, rate: str = "+0%") -> VoiceProfile:
    """edge 后端的音色档案工厂。"""
    return VoiceProfile(backend="edge", params={"voice": voice, "rate": rate})


class TtsError(Exception):
    """TTS 层所有异常的基类。上层只需要捕获这一个，对应错误码 tts_error。"""

    code = "tts_error"


class TtsBackend(Protocol):
    """语音合成后端协议。所有具体后端都实现它，runtime 只依赖这个协议。"""

    def synthesize(
        self,
        text: str,
        voice: VoiceProfile,
        *,
        turn_id: str,
        segment_index: int,
        segment_total: int,
    ) -> Iterator[TtsChunk]:
        """把一句话合成一段音频，产出落盘后的分片。

        取消语义：``cancel(turn_id)`` 之后，本方法在下一次产出前停止迭代，
        不抛异常，并清理尚未交付的半成品文件。
        """
        ...

    def cancel(self, turn_id: str) -> None:
        """请求取消某个回合的合成。幂等。"""
        ...


def split_sentences(text: str) -> list[str]:
    """把回复切成句子，供 runtime 逐句交给 TTS。

    规则：
    - 中文句末标点、英文句点/问号/感叹号是边界
    - 英文句点后面必须是空白或结尾才算边界，避免拆开 3.14、2.0
    - 换行也算边界
    - 连续标点归并进同一句
    """
    normalized = text.replace("\r\n", "\n").replace("\r", "\n")

    sentences: list[str] = []
    start = 0
    index = 0
    while index < len(normalized):
        if _is_sentence_end(normalized, index):
            end = index + 1
            while end < len(normalized) and _is_sentence_end(normalized, end):
                end += 1
            sentence = normalized[start:end].strip()
            if sentence:
                sentences.append(sentence)
            start = end
            index = end
            continue
        index += 1

    tail = normalized[start:].strip()
    if tail:
        sentences.append(tail)
    return sentences
