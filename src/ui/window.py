"""PyQt5 主窗口：只负责"显示"和"把用户动作变成信号"。

这是全项目里唯二 import PyQt5 的文件（另一个是 ``main.py``）。所以这里不许放
判断逻辑：显示状态在 ``ui/state.py`` 里算好，这里照着画。pyproject.toml 的
coverage omit 把本文件排除在覆盖率之外，理由和 stage/renderer.py 一样——
CI 里没有显示器，也不装 GUI 依赖（docs/adr/0002）。
"""

from __future__ import annotations

import html

from PyQt5.QtCore import pyqtSignal
from PyQt5.QtWidgets import (
    QHBoxLayout,
    QLabel,
    QLineEdit,
    QPushButton,
    QTextBrowser,
    QVBoxLayout,
    QWidget,
)

from events import Event
from ui.state import ConversationView

#: 助手气泡上的提示文字。
CANCELLED_NOTE = "（已打断）"
WAITING_NOTE = "…"


class ChatWindow(QWidget):
    """一个窗口：上方一行信息，中间对话记录，下面状态栏与输入行。"""

    #: 用户按下发送（或回车）。参数是输入框里的原文。
    user_submitted = pyqtSignal(str)
    #: 用户按下停止。
    stop_requested = pyqtSignal()
    #: 事件从工作线程投递到界面线程的唯一通道：工作线程 emit，Qt 会自动排队，
    #: 槽在界面线程里执行。runtime 的 send() 跑在后台线程里，不能直接碰控件。
    event_received = pyqtSignal(object)

    def __init__(self, *, character_name: str, info_text: str = "") -> None:
        super().__init__()
        self._character_name = character_name
        self._view = ConversationView()

        self.setWindowTitle(f"Live2D 数字角色 · {character_name}")
        self.resize(420, 560)

        self._info = QLabel(info_text)
        self._info.setStyleSheet("color: #666;")
        self._info.setWordWrap(True)

        self._transcript = QTextBrowser()
        self._transcript.setOpenExternalLinks(False)

        self._status = QLabel()

        self._error = QLabel()
        self._error.setStyleSheet("color: #b00;")
        self._error.setWordWrap(True)
        self._error.hide()

        self._input = QLineEdit()
        self._input.setPlaceholderText("说点什么，回车发送")
        self._send = QPushButton("发送")
        self._stop = QPushButton("停止")
        self._stop.setEnabled(False)

        row = QHBoxLayout()
        row.addWidget(self._input, 1)
        row.addWidget(self._send)
        row.addWidget(self._stop)

        layout = QVBoxLayout(self)
        layout.addWidget(self._info)
        layout.addWidget(self._transcript, 1)
        layout.addWidget(self._status)
        layout.addWidget(self._error)
        layout.addLayout(row)

        self._send.clicked.connect(self._emit_input)
        self._input.returnPressed.connect(self._emit_input)
        self._stop.clicked.connect(self.stop_requested.emit)
        # 界面线程这一侧接上画图函数。event_received 本身可以跨线程 emit。
        self.event_received.connect(self.apply_event)

        self._render()

    def apply_event(self, event: Event) -> None:
        """槽：吃一条事件并重画。跨线程 emit 时会自动排到界面线程执行。"""
        if self._view.apply(event):
            self._render()

    def view_state(self) -> ConversationView:
        """当前显示状态（冒烟时"界面确实收到了事件"就是看这个）。"""
        return self._view

    # ------------------------------------------------------------------ #
    # 内部
    # ------------------------------------------------------------------ #

    def _emit_input(self) -> None:
        """发送：把原文交给上层，然后清空输入框。是否真的开跑由上层决定。"""
        text = self._input.text().strip()
        if not text:
            return
        self._input.clear()
        self.user_submitted.emit(text)

    def _render(self) -> None:
        """照着手里的状态重画。唯一的画图入口。"""
        blocks = [
            self._render_entry(entry.role, entry.text, entry.status) for entry in self._view.entries
        ]
        self._transcript.setHtml("".join(blocks))
        scrollbar = self._transcript.verticalScrollBar()
        # 类型标注上它是可空的；真跑起来一定有。判一下免得让 mypy 挡住 CI。
        if scrollbar is not None:
            scrollbar.setValue(scrollbar.maximum())

        status = f"状态：{self._view.status}"
        if self._view.last_emotion:
            status += f" · {self._view.last_emotion}"
        self._status.setText(status)

        error = self._view.last_error
        self._error.setText(f"⚠ {error}" if error else "")
        self._error.setVisible(bool(error))

        self._stop.setEnabled(self._view.busy)

    def _render_entry(self, role: str, text: str, status: str) -> str:
        """一条消息 → 一段 HTML。"""
        name = "我" if role == "user" else self._character_name
        body = html.escape(text).replace("\n", "<br/>")
        if status == "cancelled":
            body += f' <span style="color:#999;">{CANCELLED_NOTE}</span>'
        if not text:
            body = f'<span style="color:#999;">{WAITING_NOTE}</span>'
        separator = "<hr/>" if role == "assistant" else ""
        return f"{separator}<p><b>{name}：</b>{body}</p>"
