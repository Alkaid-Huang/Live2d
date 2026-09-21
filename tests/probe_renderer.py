"""手动冒烟探针：单独验证渲染子进程能不能把模型加载起来。

**CI 不跑这个文件**（名字不是 test_*，pytest 不会收集），因为它需要显示器和
GUI 依赖，而 CI 两样都没有（docs/adr/0002）。用它是为了把"渲染进程起不来"和
"界面装配错了"分开——这两件事的表现很像，原因完全不同。

用法（在项目根目录）：

    .venv\\Scripts\\python.exe tests\\probe_renderer.py

输出约定：
- ``renderer.ready`` —— 模型加载成功，窗口已经画出来了
- ``renderer.failed`` —— 加载失败，但进程还活着（按契约退化成无模型展示）
- ``进程退出码 N`` —— 进程压根没起来，通常是缺 pygame / live2d-py
"""

from __future__ import annotations

import multiprocessing
import queue
import sys
import time
from pathlib import Path
from typing import Any

REPO_ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(REPO_ROOT / "src"))

from config import Settings  # noqa: E402
from stage import QuitCommand, message_from_payload  # noqa: E402

#: 等第一条回传的上限。首次加载要解 moc3 和两张 2048 贴图，给得宽松些。
READY_TIMEOUT_SECONDS = 20.0
#: 窗口留给人工看一眼的时间。
LINGER_SECONDS = 3.0


def main() -> int:
    """起一个渲染子进程，等它的第一条回传，然后让它退出。"""
    settings = Settings()
    model_path = _resolve(settings.live2d_model_path)
    _require(model_path)

    context = multiprocessing.get_context("spawn")
    command_queue = context.Queue()
    message_queue = context.Queue()
    process = context.Process(
        target=_run_renderer,
        kwargs={
            "model_path": str(model_path),
            "width": settings.live2d_window_width,
            "height": settings.live2d_window_height,
            "command_queue": command_queue,
            "message_queue": message_queue,
        },
        name="probe-renderer",
    )
    process.start()

    verdict = _wait_for_first_message(process, message_queue)
    print(f"结论：{verdict}")

    if process.is_alive():
        time.sleep(LINGER_SECONDS)
        command_queue.put(QuitCommand().to_payload())
        process.join(timeout=5.0)
        if process.is_alive():
            print("渲染进程没有自己退出，强制结束")
            process.terminate()
            process.join(timeout=2.0)

    return 0 if verdict.startswith("renderer.ready") else 1


def _resolve(value: str) -> Path:
    """相对路径按项目根解析（和 main.py 的 _resolve_path 同一个理由）。"""
    path = Path(value)
    return path if path.is_absolute() else REPO_ROOT / path


def _require(model_path: Path) -> None:
    """模型不在就早点说清楚，别让子进程的报错盖住真正的原因。"""
    if model_path.exists():
        return
    print(f"模型路径不存在：{model_path}")
    print("按 docs/product.md 的「技术风险」准备素材，或改 .env 的 LIVE2D_MODEL_PATH。")
    raise SystemExit(2)


def _wait_for_first_message(process: Any, message_queue: Any) -> str:
    """等渲染进程的第一条回传；进程先死就报退出码。"""
    deadline = time.monotonic() + READY_TIMEOUT_SECONDS
    while time.monotonic() < deadline:
        if not process.is_alive():
            return f"进程退出码 {process.exitcode}（渲染进程没起来）"
        try:
            raw = message_queue.get(timeout=0.2)
        except queue.Empty:
            continue
        if not isinstance(raw, dict):
            print(f"忽略无法识别的回传：{raw!r}")
            continue
        message = message_from_payload(raw)
        print(f"收到回传：{message!r}")
        return str(message.type)
    return f"超时（{READY_TIMEOUT_SECONDS:.0f}s 内没有任何回传）"


def _run_renderer(
    *,
    model_path: str,
    width: int,
    height: int,
    command_queue: Any,
    message_queue: Any,
) -> int:
    """子进程侧入口。包一层，保证子进程也先把 src 加进 sys.path。"""
    if str(REPO_ROOT / "src") not in sys.path:
        sys.path.insert(0, str(REPO_ROOT / "src"))

    from stage import run_renderer_process

    return run_renderer_process(
        model_path=model_path,
        width=width,
        height=height,
        command_queue=command_queue,
        message_queue=message_queue,
    )


if __name__ == "__main__":
    raise SystemExit(main())
