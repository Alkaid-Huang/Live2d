"""守住"CI 不装 GUI 依赖也能 import 协议层"这条性质。

跑在子进程里是为了拿到干净的 sys.modules：本机装了 pygame 时，同一个进程里
别的测试可能已经把它导进来了，那样测出来的是假的。
"""

from __future__ import annotations

import subprocess
import sys
from pathlib import Path

SRC = Path(__file__).resolve().parents[1] / "src"

PROBE = """
import sys
sys.path.insert(0, {src!r})

import stage
import stage.channel
import stage.cues
import stage.lipsync
import stage.model_files
import stage.playback
import stage.protocol

leaked = [name for name in ("pygame", "live2d", "OpenGL") if name in sys.modules]
assert not leaked, "import stage 把 GUI/渲染库拉进来了：" + ", ".join(leaked)
assert "stage.renderer" not in sys.modules, "renderer 必须惰性导入"
print("ok")
"""


def test_importing_stage_does_not_pull_in_gui_or_render_libraries() -> None:
    result = subprocess.run(
        [sys.executable, "-c", PROBE.format(src=str(SRC))],
        capture_output=True,
        text=True,
        check=False,
    )

    assert result.returncode == 0, result.stderr
    assert "ok" in result.stdout
