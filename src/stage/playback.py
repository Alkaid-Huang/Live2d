"""播放排队：决定"现在该播哪一段"，不碰 pygame。

单独成层的理由是一个边界情况：取消回合时不能只停"正在播的那段"，还得把已经
排进队列、属于同一回合的后续分段全部丢掉，否则取消之后还会冒出半句话，违反
docs/contracts.md 第 3 节的"turn.cancelled 之后不再有该回合的事件"。
这个判断值得单独测，而不是埋在渲染循环里。
"""

from __future__ import annotations

from collections import deque
from dataclasses import dataclass, field


@dataclass(frozen=True, slots=True)
class PendingChunk:
    """等待播放的一段音频。"""

    turn_id: str
    segment_index: int
    path: str


@dataclass
class PlaybackPlanner:
    """待播队列 + 当前在播的那一段。"""

    _pending: deque[PendingChunk] = field(default_factory=deque)
    _current: PendingChunk | None = None

    @property
    def current(self) -> PendingChunk | None:
        """正在播的那一段；没有就是 None。"""
        return self._current

    @property
    def has_pending(self) -> bool:
        """还有排队等着的分段吗。"""
        return bool(self._pending)

    def push(self, chunk: PendingChunk) -> None:
        """排入一段音频。"""
        self._pending.append(chunk)

    def take_next(self) -> PendingChunk | None:
        """当前没有在播时取出下一段；已经在播就返回 None。"""
        if self._current is not None or not self._pending:
            return None
        self._current = self._pending.popleft()
        return self._current

    def finish_current(self) -> None:
        """当前这一段播完了。"""
        self._current = None

    def stop(self, turn_id: str) -> PendingChunk | None:
        """丢掉某个回合的待播分段，并在它正被播放时把它停掉。

        Args:
            turn_id: 要停的回合；空串表示"不管哪一个回合，全停"。

        Returns:
            PendingChunk | None: 需要立刻停止播放的那一段；没有则 None。
        """
        if not turn_id:
            self._pending.clear()
        else:
            self._pending = deque(chunk for chunk in self._pending if chunk.turn_id != turn_id)
            current = self._current
            if current is not None and current.turn_id != turn_id:
                # 正在播的是别的回合，不该被这次取消波及。
                return None

        current, self._current = self._current, None
        return current
