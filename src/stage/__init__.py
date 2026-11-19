"""舞台层：把角色的声音和表情呈现出来。

包名故意**不叫** ``live2d``：第三方库 ``live2d-py`` 提供的顶层模块正好也叫
``live2d``，同名会让 ``import live2d.v3`` 导到我们自己身上。这一层要同时
"用 live2d 库"和"叫 live2d"，只能有一个名字胜出，所以项目这边改名。

这个包的 ``__init__`` **不许** import pygame 或 live2d：CI 不装 GUI 依赖，却要
能 import ``stage.protocol`` 来测协议本身。真正需要 pygame 的只有
``stage.renderer``，它由 ``run_renderer_process()`` 在子进程里惰性导入
——和 ``tts/__init__.py`` 装配 edge 后端是同一套写法。

边界由 tests/test_layer_boundaries.py 守着：``src/stage/`` 被允许 import
pygame / live2d / OpenGL，其他层不行。
"""

from __future__ import annotations

from pathlib import Path

from stage.channel import QueueLike, RendererChannel
from stage.cues import (
    MOTION_PRIORITY_NORMAL,
    ModelCapabilities,
    normalize_capabilities,
    resolve_label,
    select_expression,
    select_motion,
)
from stage.lipsync import (
    FRAME_MS,
    MouthDriver,
    compute_envelope,
    envelope_duration_ms,
    mouth_value,
)
from stage.model_files import MODEL_JSON_SUFFIXES, ModelNotFound, resolve_model_json
from stage.playback import PendingChunk, PlaybackPlanner
from stage.protocol import (
    AudioIdleMessage,
    AudioStartedMessage,
    Command,
    PlayAudioCommand,
    QuitCommand,
    RendererFailedMessage,
    RendererMessage,
    RendererReadyMessage,
    SetEmotionCommand,
    StopAudioCommand,
    command_from_payload,
    message_from_payload,
    message_to_events,
    message_to_payload,
)

__all__ = [
    "FRAME_MS",
    "MODEL_JSON_SUFFIXES",
    "MOTION_PRIORITY_NORMAL",
    "AudioIdleMessage",
    "AudioStartedMessage",
    "Command",
    "RendererMessage",
    "ModelCapabilities",
    "ModelNotFound",
    "MouthDriver",
    "PendingChunk",
    "PlayAudioCommand",
    "PlaybackPlanner",
    "QueueLike",
    "QuitCommand",
    "RendererChannel",
    "RendererFailedMessage",
    "RendererReadyMessage",
    "SetEmotionCommand",
    "StopAudioCommand",
    "command_from_payload",
    "compute_envelope",
    "envelope_duration_ms",
    "message_from_payload",
    "message_to_events",
    "message_to_payload",
    "mouth_value",
    "normalize_capabilities",
    "resolve_label",
    "resolve_model_json",
    "run_renderer_process",
    "select_expression",
    "select_motion",
]


def run_renderer_process(
    *,
    model_path: str | Path,
    width: int,
    height: int,
    command_queue: QueueLike,
    message_queue: QueueLike,
) -> int:  # pragma: no cover - 只能在装了 GUI 依赖、且有显示器的机器上跑（见 adr/0002）
    """渲染子进程入口。

    ``multiprocessing`` 在 Windows 上是 spawn 语义：子进程会重新 import 本模块，
    所以 pygame 与 live2d 必须等到真正要画窗口时（也就是这个函数体里）才导进来，
    否则主进程一 import ``live2d`` 就跟着把 GUI 依赖拉起来了。
    """
    from stage.renderer import run

    return run(
        model_path=model_path,
        width=width,
        height=height,
        command_queue=command_queue,
        message_queue=message_queue,
    )
