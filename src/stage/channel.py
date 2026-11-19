"""主进程侧的播放通道：往渲染进程发命令、收它回传的消息。

它实现 ``runtime.PlaybackControl`` 那两个方法（``play`` / ``stop``），所以 runtime
不需要知道渲染进程的存在，更不需要 import 这个包里的其他东西。

队列只用到 ``put`` / ``get_nowait`` 两个方法，所以这里不依赖 multiprocessing：
测试传一个列表包装的假队列就够了，真身是 ``multiprocessing.Queue``。
"""

from __future__ import annotations

import logging
import queue
from collections.abc import Mapping

from contracts import QueueLike as QueueLike
from stage.protocol import (
    PlayAudioCommand,
    QuitCommand,
    RendererMessage,
    SetEmotionCommand,
    StopAudioCommand,
    message_from_payload,
)

logger = logging.getLogger(__name__)


class RendererChannel:
    """一个渲染子进程的两条队列。"""

    def __init__(self, *, command_queue: QueueLike, message_queue: QueueLike) -> None:
        self._commands = command_queue
        self._messages = message_queue

    def play(
        self,
        *,
        turn_id: str,
        segment_index: int,
        segment_total: int,
        path: str,
        format: str,
    ) -> None:
        """交给渲染进程播一段音频（runtime 在派发每个分片时调用）。"""
        self._commands.put(
            PlayAudioCommand(
                turn_id=turn_id,
                segment_index=segment_index,
                segment_total=segment_total,
                path=path,
                format=format,
            ).to_payload()
        )

    def stop(self, turn_id: str) -> None:
        """立刻停止播放、口型归位。``turn_id`` 为空串表示全停。"""
        self._commands.put(StopAudioCommand(turn_id=turn_id).to_payload())

    def set_emotion(self, *, turn_id: str, label: str) -> None:
        """让角色换上对应情感的表情与动作（runtime 在 emotion.detected 时调用）。"""
        self._commands.put(SetEmotionCommand(turn_id=turn_id, label=label).to_payload())

    def quit(self) -> None:
        """让渲染进程收尾退出。"""
        self._commands.put(QuitCommand().to_payload())

    def drain_messages(self) -> tuple[RendererMessage, ...]:
        """取走渲染进程这段时间回传的全部消息（不阻塞）。

        队列里可能出现无法解析的东西（对象不对、字段缺了、版本不匹配）。这类消息
        只记一条 warning 就丢掉：让界面因为一条坏消息崩掉，比丢一条播放状态更糟。
        """
        messages: list[RendererMessage] = []
        while True:
            try:
                raw = self._messages.get_nowait()
            except queue.Empty:
                return tuple(messages)
            if not isinstance(raw, Mapping):
                logger.warning("忽略无法识别的渲染回传：%r", raw)
                continue
            try:
                messages.append(message_from_payload(raw))
            except ValueError as exc:
                logger.warning("忽略无法解析的渲染回传（%s）：%r", exc, raw)
