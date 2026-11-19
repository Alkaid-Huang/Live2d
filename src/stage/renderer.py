"""渲染子进程：pygame + OpenGL + live2d-py 的薄壳。

这是全项目唯一在 CI 里跑不了的文件（没有显示器，也不装 GUI 依赖，见
docs/adr/0002）。所以它必须保持"薄"：判断逻辑都在 protocol / playback /
lipsync / cues / model_files 里，这里只负责"取命令 → 调纯函数 → 画一帧"。
要往这里加逻辑之前，先想"这段能不能搬进上面某个模块"。

模型加载失败时**不许退出**：按 docs/contracts.md 第 5 节退化成无模型展示
（窗口还在、文字照常），同时回一条 renderer.failed 让界面知道。
"""

from __future__ import annotations

import logging
import queue
import time
from collections.abc import Mapping
from dataclasses import dataclass
from pathlib import Path
from typing import Any

import live2d.v3 as live2d
import pygame

from stage.channel import QueueLike
from stage.cues import (
    MOTION_PRIORITY_NORMAL,
    ModelCapabilities,
    normalize_capabilities,
    resolve_label,
    select_expression,
    select_motion,
)
from stage.lipsync import MouthDriver, compute_envelope, mouth_value
from stage.model_files import resolve_model_json
from stage.playback import PendingChunk, PlaybackPlanner
from stage.protocol import (
    LIVE2D_LOAD_FAILED,
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
    message_to_payload,
)

logger = logging.getLogger(__name__)

#: 渲染帧率。60 足够顺，也不至于让一个文本应用空转烧 CPU。
TARGET_FPS = 60

#: mixer 的格式。``Sound.get_raw()`` 返回的就是这个格式的采样，口型包络按它算。
MIXER_SAMPLE_RATE = 44100
MIXER_CHANNELS = 2
MIXER_BUFFER = 512

#: 嘴张开参数，对应 live2d.v3.StandardParams.ParamMouthOpenY。
MOUTH_PARAM_ID = "ParamMouthOpenY"


@dataclass
class _Playing:
    """当前正在播的那一段。"""

    chunk: PendingChunk
    sound: Any
    channel: Any
    envelope: tuple[float, ...]
    started_at: float


class RendererApp:
    """渲染子进程的全部状态。方法都很短，逻辑一律不在这里。"""

    def __init__(
        self,
        *,
        model_path: str | Path,
        width: int,
        height: int,
        command_queue: QueueLike,
        message_queue: QueueLike,
    ) -> None:
        self._model_path = Path(model_path)
        self._width = width
        self._height = height
        self._commands = command_queue
        self._messages = message_queue
        self._planner = PlaybackPlanner()
        self._mouth = MouthDriver()
        self._playing: _Playing | None = None
        self._model: Any | None = None
        self._capabilities = ModelCapabilities()
        self._clock: Any = pygame.time.Clock()

    # ------------------------------------------------------------------ #
    # 对外
    # ------------------------------------------------------------------ #

    def run(self) -> int:
        """开窗、加载模型、跑循环。返回进程退出码。"""
        self._open_window()
        self._load_model()
        try:
            self._loop()
        finally:
            self._shutdown()
        return 0

    def report_start_failure(self, exc: BaseException) -> None:
        """窗口都开不起来时的最后一条回传（比如没有显示器、驱动缺失）。"""
        self._send(
            RendererFailedMessage(
                code=LIVE2D_LOAD_FAILED,
                message=f"渲染进程启动失败：{type(exc).__name__}: {exc}",
            )
        )

    # ------------------------------------------------------------------ #
    # 回传
    # ------------------------------------------------------------------ #

    def _send(self, message: RendererMessage) -> None:
        try:
            self._messages.put_nowait(message_to_payload(message))
        except Exception:  # 队列满/对面已退出：报状态失败不能把画面卡住
            logger.warning("渲染状态回传失败：%s", type(message).__name__)

    # ------------------------------------------------------------------ #
    # 主循环
    # ------------------------------------------------------------------ #

    def _loop(self) -> None:
        while True:
            dt_seconds = self._clock.tick(TARGET_FPS) / 1000.0
            if not self._handle_window_events():
                return
            if not self._handle_commands():
                return
            self._advance_playback()
            self._update_mouth(dt_seconds)
            self._draw()

    def _handle_window_events(self) -> bool:
        """处理窗口事件。返回 False 表示用户关掉了窗口。"""
        return all(event.type != pygame.QUIT for event in pygame.event.get())

    def _handle_commands(self) -> bool:
        """处理队列里现有的全部命令。返回 False 表示该退出了。"""
        while True:
            try:
                raw = self._commands.get_nowait()
            except queue.Empty:
                return True
            if not isinstance(raw, Mapping):
                logger.warning("忽略无法识别的渲染命令：%r", raw)
                continue
            try:
                command: Command = command_from_payload(raw)
            except ValueError as exc:
                logger.warning("忽略无法解析的渲染命令（%s）：%r", exc, raw)
                continue
            if isinstance(command, QuitCommand):
                return False
            if isinstance(command, PlayAudioCommand):
                self._planner.push(
                    PendingChunk(
                        turn_id=command.turn_id,
                        segment_index=command.segment_index,
                        path=command.path,
                    )
                )
            elif isinstance(command, StopAudioCommand):
                self._stop_playback(command.turn_id)
            elif isinstance(command, SetEmotionCommand):
                self._apply_emotion(command)
        return True

    # ------------------------------------------------------------------ #
    # 表情与动作
    # ------------------------------------------------------------------ #

    def _apply_emotion(self, command: SetEmotionCommand) -> None:
        """换表情并按情感播一个动作。

        无模型展示时整段跳过：文字照常，只是没有脸。这里不报错也不回传。
        """
        if self._model is None:
            return
        cue = resolve_label(command.label)
        expression = select_expression(self._capabilities, cue)
        if expression is not None:
            self._model.SetExpression(expression)
        group = select_motion(self._capabilities, cue)
        if group is not None:
            self._model.StartRandomMotion(group, MOTION_PRIORITY_NORMAL)

    # ------------------------------------------------------------------ #
    # 播放
    # ------------------------------------------------------------------ #

    def _advance_playback(self) -> None:
        """推进播放：播完一段就报 idle 并接上下一段。"""
        playing = self._playing
        if playing is not None and not playing.channel.get_busy():
            self._planner.finish_current()
            self._playing = None
            self._mouth.reset()
            if not self._planner.has_pending:
                self._send(AudioIdleMessage(turn_id=playing.chunk.turn_id))

        if self._playing is None:
            chunk = self._planner.take_next()
            if chunk is not None:
                self._start_playback(chunk)

    def _start_playback(self, chunk: PendingChunk) -> None:
        try:
            sound = pygame.mixer.Sound(chunk.path)
            sound.set_volume(1.0)
            channel = sound.play()
        except Exception:
            # 单个分片播不出来不是致命问题：丢掉它，别让整条链路停下。
            logger.exception("音频播放失败，跳过这一段：%s", chunk.path)
            self._planner.finish_current()
            return

        self._playing = _Playing(
            chunk=chunk,
            sound=sound,
            channel=channel,
            envelope=compute_envelope(
                sound.get_raw(),
                sample_rate=MIXER_SAMPLE_RATE,
                channels=MIXER_CHANNELS,
            ),
            started_at=time.monotonic(),
        )
        self._send(AudioStartedMessage(turn_id=chunk.turn_id, segment_index=chunk.segment_index))

    def _stop_playback(self, turn_id: str) -> None:
        """立刻停止播放、口型归位。待播队列里同回合的分段一起丢掉。"""
        stopped = self._planner.stop(turn_id)
        if stopped is None:
            return
        playing = self._playing
        if playing is not None:
            try:
                playing.channel.stop()
            except Exception:
                logger.debug("停止播放时出错", exc_info=True)
        self._playing = None
        self._mouth.reset()
        self._send(AudioIdleMessage(turn_id=stopped.turn_id))

    def _update_mouth(self, dt_seconds: float) -> None:
        """按播放进度取目标张嘴幅度，平滑后写进模型参数。"""
        target = 0.0
        playing = self._playing
        if playing is not None:
            elapsed_ms = (time.monotonic() - playing.started_at) * 1000.0
            target = mouth_value(playing.envelope, elapsed_ms)
        value = self._mouth.update(target, dt_seconds)
        if self._model is not None:
            self._model.SetParameterValue(MOUTH_PARAM_ID, value)

    # ------------------------------------------------------------------ #
    # 画面与生命周期
    # ------------------------------------------------------------------ #

    def _draw(self) -> None:
        """每帧把模型画出来。背景与字幕叠加留给 M1-6。"""
        live2d.clearBuffer()
        if self._model is not None:
            self._model.Update()
            self._model.Draw()
        pygame.display.flip()

    def _open_window(self) -> None:
        pygame.init()
        pygame.mixer.pre_init(MIXER_SAMPLE_RATE, -16, MIXER_CHANNELS, MIXER_BUFFER)
        pygame.mixer.init()
        pygame.display.set_mode((self._width, self._height), pygame.OPENGL | pygame.DOUBLEBUF)
        pygame.display.set_caption("Live2D")
        live2d.init()
        live2d.glInit()

    def _load_model(self) -> None:
        """加载模型。失败只回传，不抛：界面要能退化成无模型展示。"""
        try:
            model_json = resolve_model_json(self._model_path)
            model = live2d.LAppModel()
            model.LoadModelJson(str(model_json))
            model.Resize(self._width, self._height)
            model.SetAutoBlinkEnable(True)
            model.SetAutoBreathEnable(True)
        except Exception as exc:
            logger.exception("Live2D 模型加载失败，退化成无模型展示")
            self._send(
                RendererFailedMessage(
                    code=LIVE2D_LOAD_FAILED,
                    message=f"{type(exc).__name__}: {exc}",
                )
            )
            return

        self._model = model
        self._capabilities = normalize_capabilities(
            model.GetMotionGroups(),
            model.GetExpressionIds(),
        )
        logger.info(
            "模型就绪：%s，动作组 %d 个，表情 %d 个",
            model_json,
            len(self._capabilities.motion_groups),
            len(self._capabilities.expressions),
        )
        self._send(RendererReadyMessage(model_path=str(model_json)))

    def _shutdown(self) -> None:
        """收尾。子进程被强杀时走不到这里，所以每一步都要能单独容错。"""
        playing = self._playing
        if playing is not None:
            try:
                playing.channel.stop()
            except Exception:
                logger.debug("退出时停止播放出错", exc_info=True)
            self._playing = None
        try:
            live2d.dispose()
        except Exception:
            logger.debug("释放 live2d 出错", exc_info=True)
        try:
            pygame.quit()
        except Exception:
            logger.debug("关闭 pygame 出错", exc_info=True)


def run(
    *,
    model_path: str | Path,
    width: int,
    height: int,
    command_queue: QueueLike,
    message_queue: QueueLike,
) -> int:
    """子进程入口。``run_renderer_process()`` 调它；直接调也可以用来手测。"""
    app = RendererApp(
        model_path=model_path,
        width=width,
        height=height,
        command_queue=command_queue,
        message_queue=message_queue,
    )
    try:
        return app.run()
    except Exception as exc:
        logger.exception("渲染进程异常退出")
        app.report_start_failure(exc)
        return 1
