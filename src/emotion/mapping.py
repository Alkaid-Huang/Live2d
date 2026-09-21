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
    """七分类情感标签，值就是文档里的中文名。"""

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

    motion_group 是动作组名，expression 是表情名，两者都是字符串。
    具体怎么变成 live2d-py 的参数，是渲染进程的事，这一层不碰。
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
    """把标签解析成渲染提示。未映射的标签回落到中性并记录原因。

    契约（docs/contracts.md 第 4 节）：未映射的标签回落到中性并记一条日志，
    不许静默失败。
    """
    cue = EMOTION_MAPPING.get(label)
    if cue is not None:
        return cue
    logger.warning("未映射的情感标签回落到中性：%s", label.value)
    return EMOTION_MAPPING[EmotionLabel.NEUTRAL]
