"""TTS 层的实现工具：切句与音色档案工厂。

契约（``TtsBackend``、``TtsChunk``、``VoiceProfile``、``TtsError``、``TtsState``）
定义在 :mod:`contracts`；这里把它们 re-export，让同层代码少写一行 import。
"""

from __future__ import annotations

from contracts import TtsBackend, TtsChunk, TtsError, TtsState, VoiceProfile

__all__ = [
    "TtsBackend",
    "TtsChunk",
    "TtsError",
    "TtsState",
    "VoiceProfile",
    "edge_profile",
    "split_sentences",
]

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


def edge_profile(voice: str, rate: str = "+0%") -> VoiceProfile:
    """构造 edge 后端的音色档案。

    Args:
        voice: edge 音色 id，例如 ``"zh-CN-XiaoxiaoNeural"``。
        rate: 语速，形如 ``"+0%"``、``"-10%"``，原样交给 edge。

    Returns:
        ``backend="edge"`` 的音色档案，参数放在 ``params`` 里。

    Note:
        不抛异常。

    Example:
        ```python
        profile = edge_profile("zh-CN-XiaoxiaoNeural", rate="+10%")
        assert profile.params["rate"] == "+10%"
        ```
    """
    return VoiceProfile(backend="edge", params={"voice": voice, "rate": rate})


def split_sentences(text: str) -> list[str]:
    """把回复切成句子，供 runtime 逐句交给 TTS。

    规则：中文句末标点与英文 ``.?!`` 是边界；英文句点后面必须是空白或结尾，
    避免拆开 ``3.14``、``2.0``；换行也算边界；连续标点归并进同一句。

    Args:
        text: 完整回复。

    Returns:
        去首尾空白后的非空句子列表；全是空白时返回空列表。

    Note:
        不抛异常。

    Example:
        ```python
        split_sentences("你好。今天天气不错！")
        # ['你好。', '今天天气不错！']

        split_sentences("圆周率是 3.14 左右。")
        # ['圆周率是 3.14 左右。']
        ```
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
