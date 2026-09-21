"""界面层。对外只暴露纯逻辑部分。

这里**故意不 import** ``ui.window``：那个文件要 import PyQt5，而 CI 不装 GUI
依赖（见 docs/adr/0002）。``ui.state`` 是纯 Python，CI 要能 import 它来测。
需要窗口的地方（只有 ``main.py``）自己 import ``ui.window``。
"""

from __future__ import annotations

from ui.state import ConversationView, Entry, LatencyTracker, SendQueue, TurnLatency

__all__ = [
    "ConversationView",
    "Entry",
    "LatencyTracker",
    "SendQueue",
    "TurnLatency",
]
