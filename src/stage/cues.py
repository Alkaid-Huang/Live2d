"""情感标签 → 动作组 / 表情名，以及"当前模型没有这个动作"时的回落。

只做选择，不碰渲染：输入是事件里的标签字符串和模型自报的能力清单
（``GetMotionGroups()`` / ``GetExpressionIds()`` 的结果），输出是名字或 None。
所以这一层能用普通字典测，不需要加载模型，也不需要显示器。

动作组和表情名都是抽象名字（见 docs/contracts.md 第 4 节），把它翻译成
live2d-py 的参数值是渲染进程的事。
"""

from __future__ import annotations

import logging
from collections.abc import Iterable, Mapping
from dataclasses import dataclass, field

from emotion.mapping import EmotionCue, EmotionLabel, resolve

logger = logging.getLogger(__name__)

#: 模型没有对应情感动作时退回去待机。大小写按各家模型的习惯都试一遍。
IDLE_ALIASES = ("idle", "Idle", "IDLE", "idle_motion")

#: 动作播放优先级，对应 live2d.v3.MotionPriority.NORMAL。放在这里是为了让渲染
#: 进程只出现一个数字字面量。
MOTION_PRIORITY_NORMAL = 3


@dataclass(frozen=True, slots=True)
class ModelCapabilities:
    """模型自报的能力：有哪些动作组、有哪些表情。"""

    motion_groups: tuple[str, ...] = field(default_factory=tuple)
    expressions: tuple[str, ...] = field(default_factory=tuple)

    def find_motion(self, name: str) -> str | None:
        """按名字找动作组，先精确匹配再忽略大小写。找不到返回 None。"""
        return _find(self.motion_groups, name)

    def find_expression(self, name: str) -> str | None:
        """按名字找表情，先精确匹配再忽略大小写。找不到返回 None。"""
        return _find(self.expressions, name)


def _find(names: tuple[str, ...], wanted: str) -> str | None:
    for name in names:
        if name == wanted:
            return name
    lowered = wanted.lower()
    for name in names:
        if name.lower() == lowered:
            return name
    return None


def _names(raw: object) -> tuple[str, ...]:
    """把 live2d-py 返回的原始结构整理成去重、去空的名字元组。

    不同版本返回 dict（名字在键上）或 list，也可能是 None；这些差异只在这里处理，
    渲染进程不必到处写 isinstance。
    """
    if raw is None:
        return ()
    if isinstance(raw, Mapping):
        candidates: Iterable[object] = list(raw.keys())
    elif isinstance(raw, Iterable) and not isinstance(raw, str | bytes):
        candidates = list(raw)
    else:
        return ()

    collected: list[str] = []
    for item in candidates:
        if not isinstance(item, str):
            continue
        name = item.strip()
        if name and name not in collected:
            collected.append(name)
    return tuple(collected)


def normalize_capabilities(motion_groups: object, expressions: object) -> ModelCapabilities:
    """归一化模型能力清单。"""
    return ModelCapabilities(
        motion_groups=_names(motion_groups),
        expressions=_names(expressions),
    )


def resolve_label(label: str) -> EmotionCue:
    """把事件里的标签字符串解析成渲染提示。

    事件里的 label 是字符串（跨进程传输），认不出来的（空串、别的版本写进来的
    新标签）回落到中性并记一条 warning，而不是让渲染进程崩掉。
    """
    try:
        parsed = EmotionLabel(label)
    except ValueError:
        logger.warning("认不出的情感标签，回落到中性：%r", label)
        parsed = EmotionLabel.NEUTRAL
    return resolve(parsed)


def select_motion(capabilities: ModelCapabilities, cue: EmotionCue) -> str | None:
    """挑一个动作组。

    顺序：情感对应的动作组 → 待机动作组。都没有就返回 None——这不是错误，
    只是这个模型没有可用的动作，渲染进程跳过播放即可。
    """
    for name in (cue.motion_group, *IDLE_ALIASES):
        found = capabilities.find_motion(name)
        if found is not None:
            return found
    logger.warning("模型没有任何可用动作组，跳过动作：想要 %s", cue.motion_group)
    return None


def select_expression(capabilities: ModelCapabilities, cue: EmotionCue) -> str | None:
    """挑一个表情。没有就返回 None。

    这里只记 debug：免费素材的模型大多没有表情文件，每个回合刷一条 warning
    会把日志淹掉。
    """
    found = capabilities.find_expression(cue.expression)
    if found is None:
        logger.debug("模型没有表情 %s，跳过", cue.expression)
    return found
