"""情感标签到动作组/表情名的映射。

这一层只输出抽象名字（motion_group / expression），不 import 任何渲染库。
渲染进程拿到名字之后，再由它自己解析成 live2d-py 的参数（M1-5 才做）。

EmotionLabel 是七分类（与 docs/contracts.md 第 4 节一致），但 M1 只映射其中四个：
开心 / 难过 / 生气 / 中性。其余三个（惊讶 / 害怕 / 厌恶）在 EMOTION_MAPPING
里没有键，resolve() 会回落到中性并打一条 warning——这也是契约里写死的行为。
"""

from __future__ import annotations

import logging
from dataclasses import dataclass
from enum import StrEnum

logger = logging.getLogger(__name__)


class EmotionLabel(StrEnum):
    """七分类情感标签，值就是文档里用的中文名。

    Example:
        ```python
        detect("太好了！") == EmotionLabel.HAPPINESS   # True
        EmotionLabel.NEUTRAL.value                    # '中性'
        ```
    """

    HAPPINESS = "开心"
    SADNESS = "难过"
    ANGER = "生气"
    SURPRISE = "惊讶"
    FEAR = "害怕"
    DISGUST = "厌恶"
    NEUTRAL = "中性"


@dataclass(frozen=True, slots=True)
class EmotionCue:
    """一次情感判断要告诉渲染进程的两件事。

    Attributes:
        motion_group: 动作组名，例如 ``"happiness"``。
        expression: 表情名，例如 ``"smile"``。

    Note:
        两者都是抽象名字，不含任何 live2d-py 参数。

    Example:
        ```python
        resolve(EmotionLabel.HAPPINESS)
        # EmotionCue(motion_group='happiness', expression='smile')
        ```
    """

    motion_group: str
    expression: str


#: 稳定的动作组 id / 表情名。这里只放 M1 真正能区分的四类，
#: 与 docs/product.md 的 US-3「切换 2–3 种表情」保持一致。
EMOTION_MAPPING: dict[EmotionLabel, EmotionCue] = {
    EmotionLabel.HAPPINESS: EmotionCue(motion_group="happiness", expression="smile"),
    EmotionLabel.SADNESS: EmotionCue(motion_group="sadness", expression="sad"),
    EmotionLabel.ANGER: EmotionCue(motion_group="anger", expression="angry"),
    EmotionLabel.NEUTRAL: EmotionCue(motion_group="neutral", expression="neutral"),
}


def resolve(label: EmotionLabel) -> EmotionCue:
    """把标签解析成渲染提示。

    Args:
        label: 情感标签。

    Returns:
        对应的动作组与表情名。

    Note:
        不抛异常。未映射的标签回落到中性并记一条 warning。

    Example:
        ```python
        resolve(EmotionLabel.SURPRISE)   # 未映射，回落到中性
        # EmotionCue(motion_group='neutral', expression='neutral')
        ```
    """
    cue = EMOTION_MAPPING.get(label)
    if cue is not None:
        return cue
    logger.warning("未映射的情感标签回落到中性：%s", label.value)
    return EMOTION_MAPPING[EmotionLabel.NEUTRAL]
