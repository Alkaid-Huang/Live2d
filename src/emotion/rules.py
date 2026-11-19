"""关键词规则：把一段文本判成一个 EmotionLabel。

M1 用关键词规则（见 docs/product.md 与 docs/contracts.md 第 8 节），不接模型。
判断是纯函数、无副作用，方便测试。

规则的两个已知局限，写在这里而不是藏起来：

- 命中多个情绪时按固定优先级取第一个，优先级见 _PRIORITY。
- 只看字面、不看否定：例如「一点也不开心」仍会判成开心。M2 换分类模型再解决。
"""

from __future__ import annotations

from emotion.mapping import EmotionLabel

#: 每个标签的关键词。关键词要短、要少见，减少和别的标签撞车。
_KEYWORDS: dict[EmotionLabel, tuple[str, ...]] = {
    EmotionLabel.FEAR: ("害怕", "好怕", "恐怖", "吓死", "不敢", "毛骨悚然"),
    EmotionLabel.ANGER: ("生气", "气死", "火大", "可恶", "愤怒", "讨厌"),
    EmotionLabel.DISGUST: ("恶心", "反胃", "嫌弃"),
    EmotionLabel.SADNESS: ("难过", "伤心", "想哭", "呜呜", "遗憾", "委屈", "失落"),
    EmotionLabel.SURPRISE: ("竟然", "居然", "没想到", "天哪", "震惊", "惊讶"),
    EmotionLabel.HAPPINESS: ("哈哈", "嘻嘻", "开心", "高兴", "太棒", "太好了", "快乐", "喜欢"),
}

#: 命中多个时的优先级：更具体、更强烈的负面情绪先匹配。
_PRIORITY: tuple[EmotionLabel, ...] = (
    EmotionLabel.FEAR,
    EmotionLabel.ANGER,
    EmotionLabel.DISGUST,
    EmotionLabel.SADNESS,
    EmotionLabel.SURPRISE,
    EmotionLabel.HAPPINESS,
)


def detect(text: str) -> EmotionLabel:
    """把一段文本判成一个情感标签。

    Args:
        text: 要判断的文本，通常是 LLM 的完整回复。

    Returns:
        命中的第一个标签；空文本或未命中任何关键词时返回 ``中性``。

    Note:
        不抛异常。

    Note:
        命中多个标签时按 ``_PRIORITY`` 取第一个。规则只看字面、不看否定：
        「一点也不开心」仍会判成开心。

    Example:
        ```python
        detect("太好了，谢谢你！")   # EmotionLabel.HAPPINESS
        detect("今天星期二。")       # EmotionLabel.NEUTRAL
        ```
    """
    if not text:
        return EmotionLabel.NEUTRAL
    for label in _PRIORITY:
        if any(keyword in text for keyword in _KEYWORDS[label]):
            return label
    return EmotionLabel.NEUTRAL
