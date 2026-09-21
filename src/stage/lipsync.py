"""口型驱动：把音频采样变成张嘴幅度。

依据 docs/adr/0001 的派生约束：口型**只用音频音量驱动**，不用 edge-tts 的逐字
时间戳——时间戳是 edge 独有的能力，本地模型没有，现在图省事接上，将来就得
重写口型。

这一层不 import pygame 也不 import live2d：输入是一段 PCM 缓冲，输出是一串
0~1 的幅度值。测试直接喂合成出来的波形，不需要声卡、也不需要窗口。
"""

from __future__ import annotations

from array import array
from dataclasses import dataclass

#: 每个音量窗口的时长。50ms 大致是一个音节的量级：再短口型会抖，再长跟不上语速。
FRAME_MS = 50

#: 低于峰值这个比例的窗口算静音，直接闭嘴。不设它会看到"呼吸声也在张嘴"。
NOISE_FLOOR_RATIO = 0.08

#: 开方压缩动态范围：语音里轻声的部分也要张得开，否则听得到声音却看不到嘴动。
CURVE = 0.5

#: 整体增益，冒烟测试时按实际观感微调。
MOUTH_GAIN = 1.0

#: 张嘴比闭嘴快：说话要"咬得准"，停下要"慢慢合上"，否则像抽搐。
ATTACK_PER_SECOND = 18.0
RELEASE_PER_SECOND = 9.0

#: 我们用 16 位有符号 PCM（由渲染进程把 mixer 格式固定成这样）。
_SAMPLE_WIDTH = 2


def compute_envelope(
    pcm: bytes,
    *,
    sample_rate: int,
    channels: int,
    frame_ms: int = FRAME_MS,
) -> tuple[float, ...]:
    """把一段 PCM 缓冲切成固定时长的窗口，算出每个窗口的音量（0~1）。

    16 位有符号、小端、交错声道。返回空元组表示"没有可用采样"（空缓冲、
    参数不合法，或缓冲区连一个采样都放不下）。

    Raises:
        不抛异常：音量算不出来时返回空元组，渲染进程会退化成"不说话"。
    """
    if sample_rate <= 0 or channels <= 0 or frame_ms <= 0:
        return ()

    usable = len(pcm) - len(pcm) % _SAMPLE_WIDTH
    if usable <= 0:
        return ()
    samples = array("h")
    samples.frombytes(pcm[:usable])

    samples_per_frame = max(1, sample_rate * frame_ms // 1000) * channels
    levels: list[float] = []
    for start in range(0, len(samples), samples_per_frame):
        window = samples[start : start + samples_per_frame]
        total = 0.0
        for value in window:
            total += float(value) * float(value)
        levels.append((total / len(window)) ** 0.5)

    peak = max(levels)
    if peak <= 0.0:
        # 全静音。给出一串 0 而不是空元组：长度信息是调用方判断"播完了"的依据。
        return tuple(0.0 for _ in levels)

    floor = peak * NOISE_FLOOR_RATIO
    return tuple(
        0.0 if level < floor else min(1.0, MOUTH_GAIN * (level / peak) ** CURVE)
        for level in levels
    )


def envelope_duration_ms(envelope: tuple[float, ...], *, frame_ms: int = FRAME_MS) -> float:
    """包络覆盖的时长。渲染进程用它判断"这一段播完了"。"""
    return len(envelope) * frame_ms


def mouth_value(
    envelope: tuple[float, ...],
    elapsed_ms: float,
    *,
    frame_ms: int = FRAME_MS,
) -> float:
    """取 ``elapsed_ms`` 时刻的目标张嘴幅度。

    超出包络范围返回 0：播完了就该闭嘴，不该卡在最后一个值上张着嘴。
    """
    if elapsed_ms < 0 or not envelope:
        return 0.0
    index = int(elapsed_ms // frame_ms)
    if index >= len(envelope):
        return 0.0
    return envelope[index]


@dataclass
class MouthDriver:
    """把目标幅度变成平滑的实际幅度：快张慢闭。

    状态只有一个数，所以给一个目标加一个时间步长就能断言结果。
    """

    value: float = 0.0

    def update(
        self,
        target: float,
        dt_seconds: float,
        *,
        attack_per_second: float = ATTACK_PER_SECOND,
        release_per_second: float = RELEASE_PER_SECOND,
    ) -> float:
        """朝目标走一步，返回新的张开度。超调不会发生：一步最多走到目标。"""
        goal = min(1.0, max(0.0, target))
        rate = attack_per_second if goal > self.value else release_per_second
        step = max(0.0, rate * dt_seconds)
        delta = goal - self.value
        if abs(delta) <= step:
            self.value = goal
        else:
            self.value += step if delta > 0 else -step
        return self.value

    def reset(self) -> None:
        """立刻闭嘴（取消回合或停止播放时用）。"""
        self.value = 0.0
