"""情感层。对外只暴露规则与映射的入口和数据结构。"""

from emotion.mapping import EMOTION_MAPPING, EmotionCue, EmotionLabel, resolve
from emotion.rules import detect

__all__ = ["EMOTION_MAPPING", "EmotionCue", "EmotionLabel", "detect", "resolve"]
