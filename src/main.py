"""桌面入口：把所有部件装起来。

装配顺序：配置 → 队列 → 渲染子进程 → 通道 → runtime → 窗口 → 定时器。

这个文件是"装配车间"，不是逻辑层：它 import PyQt5（硬约束 1 对 main.py 放行
GUI 包），但**不许** import pygame / live2d / edge_tts —— 渲染依赖留给
stage/renderer.py（在子进程里惰性导入），语音后端留给 tts/edge_impl.py。
pyproject.toml 的 coverage omit 把它排除在覆盖率之外，理由同 ui/window.py。

Windows 的 spawn 语义会重新 import 本模块（作为 ``__mp_main__``），所以**模块顶层
不许有副作用**：一切都在 ``main()`` 里做，且只有 ``__main__`` 时才调用。
"""

from __future__ import annotations

import logging
import multiprocessing
import sys
import threading
from pathlib import Path
from typing import cast

from PyQt5.QtCore import QTimer
from PyQt5.QtWidgets import QApplication

from config import PROJECT_ROOT, Settings
from events import ErrorEvent, Event, TurnCancelledEvent, TurnDoneEvent
from runtime import ChatRuntime
from stage import RendererChannel, message_to_events, run_renderer_process
from stage.channel import QueueLike
from stage.protocol import LIVE2D_LOAD_FAILED
from tts import create_tts_backend, edge_profile
from ui.state import LatencyTracker, SendQueue
from ui.window import ChatWindow

logger = logging.getLogger(__name__)

#: 角色名。M1 写死，M2 跟着角色描述一起做成可配置（runtime 里的 system prompt 同理）。
CHARACTER_NAME = "角色"

#: 渲染进程的启动看门狗：过了这么久它还不活着，就按"无模型展示"处理。
RENDERER_WATCHDOG_MS = 2000
#: 轮询渲染进程回传的间隔。只有几条状态消息，用不着更密。
MESSAGE_POLL_MS = 100
#: 退出时等渲染进程自己收尾的时间。
SHUTDOWN_JOIN_SECONDS = 3.0


def main(argv: list[str] | None = None) -> int:
    """启动桌面程序，返回退出码。"""
    settings = Settings()
    _setup_logging(settings.log_level)

    model_path = _resolve_path(settings.live2d_model_path)
    audio_dir = _resolve_path(settings.tts_audio_dir)
    audio_dir.mkdir(parents=True, exist_ok=True)
    logger.info("模型路径：%s", model_path)
    logger.info("临时音频目录：%s", audio_dir)

    # 队列必须由同一个 context 造出来：Windows 的 spawn 不接受把别的 context
    # 造出来的队列传进子进程（docs/contracts.md 第 1 节）。
    context = multiprocessing.get_context("spawn")
    command_queue = context.Queue()
    message_queue = context.Queue()
    renderer_process = context.Process(
        target=run_renderer_process,
        kwargs={
            "model_path": str(model_path),
            "width": settings.live2d_window_width,
            "height": settings.live2d_window_height,
            "command_queue": command_queue,
            "message_queue": message_queue,
        },
        name="live2d-renderer",
        daemon=True,
    )
    renderer_process.start()
    channel = RendererChannel(
        command_queue=_as_queue(command_queue),
        message_queue=_as_queue(message_queue),
    )

    backend = create_tts_backend(settings.tts_backend, audio_dir=audio_dir)
    voice = edge_profile(settings.tts_edge_voice, settings.tts_edge_rate)

    app = QApplication(argv if argv is not None else sys.argv)
    window = ChatWindow(
        character_name=CHARACTER_NAME,
        info_text=(
            f"模型 {model_path.name} · 语音 {settings.tts_backend}"
            f"（{settings.tts_edge_voice}） · 大模型 {settings.llm_provider}/{settings.llm_model}"
        ),
    )

    send_queue = SendQueue()
    latency = LatencyTracker()

    def run_turn(text: str) -> None:
        """把一次 send() 放进后台线程。runtime 自己会兜住所有业务异常。"""
        thread = threading.Thread(
            target=_send_and_log,
            args=(runtime, text),
            name="turn",
            daemon=True,
        )
        thread.start()

    def dispatch(event: Event) -> None:
        """所有事件的唯一出口。可能被回合线程或界面线程调用。"""
        summary = latency.observe(event)
        if summary is not None:
            logger.info(
                "回合 %s 用时：首字 %s / 首音 %s / 整轮 %d ms",
                summary.turn_id[:8],
                _ms_text(summary.first_token_ms),
                _ms_text(summary.first_audio_ms),
                summary.total_ms,
            )
        # 跨线程交给界面：emit 是线程安全的，窗口那边会自动排队。
        window.event_received.emit(event)
        if isinstance(event, TurnDoneEvent | TurnCancelledEvent):
            pending = send_queue.take_after_turn()
            if pending is not None:
                run_turn(pending)

    runtime = ChatRuntime(
        sink=dispatch,
        tts_backend=backend,
        settings=settings,
        voice=voice,
        renderer=channel,
    )

    def on_submitted(text: str) -> None:
        """用户发了消息：空闲就直接开跑，忙就先取消当前回合再排队。"""
        decision = send_queue.submit(text, active_turn_id=runtime.active_turn_id)
        if decision.cancel_turn_id is not None:
            # 契约要求的两件事都由 runtime 负责：停合成、停播放（它内部会调 stop）。
            # 界面这边只负责把新文本排上，等这个回合收尾后由 dispatch 放行。
            runtime.cancel(decision.cancel_turn_id, reason="user_new_message")
        if decision.start_now is not None:
            run_turn(decision.start_now)

    def on_stop_requested() -> None:
        """用户按了停止。"""
        active = runtime.active_turn_id
        if active is not None:
            runtime.cancel(active, reason="user_stop")

    window.user_submitted.connect(on_submitted)
    window.stop_requested.connect(on_stop_requested)

    def pump_renderer_messages() -> None:
        """把渲染进程的回传翻成事件（播放状态只有它知道）。"""
        for message in channel.drain_messages():
            for event in message_to_events(message):
                dispatch(event)

    pump = QTimer()
    pump.setInterval(MESSAGE_POLL_MS)
    pump.timeout.connect(pump_renderer_messages)
    pump.start()

    def check_renderer_alive() -> None:
        """渲染进程要是压根没起来，按契约降级成无模型展示，而不是跟着崩。"""
        if renderer_process.is_alive():
            return
        dispatch(
            ErrorEvent(
                turn_id="",
                code=LIVE2D_LOAD_FAILED,
                message=(
                    f"渲染进程没起来（退出码 {renderer_process.exitcode}）。"
                    '已按无模型展示继续，文字与语音照常；若是缺 GUI 依赖，'
                    '请执行 pip install -e ".[gui]"'
                ),
            )
        )

    QTimer.singleShot(RENDERER_WATCHDOG_MS, check_renderer_alive)

    def shutdown() -> None:
        """退出：停轮询、取消在跑的回合、让渲染进程收尾、清临时音频（契约第 8 节）。"""
        logger.info("正在关闭…")
        pump.stop()
        active = runtime.active_turn_id
        if active is not None:
            runtime.cancel(active, reason="user_stop")
        try:
            channel.quit()
        except Exception:  # 队列坏掉也不该挡住退出
            logger.exception("发送退出命令失败")
        renderer_process.join(timeout=SHUTDOWN_JOIN_SECONDS)
        if renderer_process.is_alive():
            logger.warning("渲染进程没有自己退出，强制结束")
            renderer_process.terminate()
            renderer_process.join(timeout=1.0)
        _cleanup_audio_dir(audio_dir)

    app.aboutToQuit.connect(shutdown)
    window.show()
    return int(app.exec_())


def _send_and_log(runtime: ChatRuntime, text: str) -> None:
    """跑一个回合。业务异常 runtime 已经翻译成事件了。"""
    try:
        runtime.send(text)
    except Exception:
        # 只剩"上一个回合还没结束"这类调用方错误，正常不该发生；
        # 真发生了也别让它在后台线程里悄无声息地消失。
        logger.exception("回合线程异常退出")


def _as_queue(queue: object) -> QueueLike:
    """``multiprocessing.Queue`` 在运行时满足 QueueLike（put / get_nowait 都有），
    但类型系统看不出来，这里转换一次，免得 RendererChannel 那边到处写 ignore。"""
    return cast(QueueLike, queue)


def _resolve_path(value: str) -> Path:
    """相对路径按项目根解析，不按工作目录。

    理由和 config.py 里的 ENV_FILE 一样：从 run.bat、快捷方式、IDE 启动时工作目录
    都可能是别的地方，届时 ``models/hiyori`` 会指到一个不存在的路径。
    """
    path = Path(value)
    return path if path.is_absolute() else PROJECT_ROOT / path


def _cleanup_audio_dir(audio_dir: Path) -> None:
    """清掉临时音频。删不掉的只记日志——退出流程不该因为一个文件失败。"""
    removed = 0
    for item in audio_dir.glob("*"):
        if not item.is_file():
            continue
        try:
            item.unlink()
        except OSError:
            logger.warning("临时音频删不掉：%s", item)
        else:
            removed += 1
    if removed:
        logger.info("清理临时音频 %d 个", removed)


def _ms_text(value: int | None) -> str:
    """延迟数字 → 日志文字。没打到的点写 n/a。"""
    return "n/a" if value is None else f"{value}ms"


def _setup_logging(level: str) -> None:
    """按配置初始化日志。级别名写错就退回 INFO，不必为此启动失败。"""
    resolved = getattr(logging, level.strip().upper(), None)
    if not isinstance(resolved, int):
        resolved = logging.INFO
    logging.basicConfig(
        level=resolved,
        format="%(asctime)s %(levelname)-7s %(name)s: %(message)s",
    )


if __name__ == "__main__":
    raise SystemExit(main())
