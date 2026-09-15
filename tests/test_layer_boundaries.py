"""把 AGENTS.md 的硬约束 1 和 2 变成 CI 能发现的错误。

- 硬约束 1：核心层不许 import GUI 或网络库
- 硬约束 2：只有 tts/edge_impl.py 允许 import edge_tts

做法是「默认禁止，显式豁免」：src/ 下的所有文件都算核心层，只有下面
EXEMPTIONS 里列出的文件可以 import 对应的库。这样以后新增模块会自动被覆盖，
不需要记得回来改这个测试——反过来，将来真的要加网络层（比如 Web 形态），
它会先失败，逼着人显式地把豁免写进来。

检查用 ast 解析而不是正则：正则会被注释、字符串和 import 的写法绕过去。
"""

from __future__ import annotations

import ast
from dataclasses import dataclass
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[1]
SRC = REPO_ROOT / "src"

#: 核心层禁止触碰的顶层包名
FORBIDDEN_PACKAGES = frozenset(
    {
        # GUI 与渲染
        "PyQt5",
        "PyQt6",
        "PySide2",
        "PySide6",
        "pygame",
        "live2d",
        "OpenGL",
        "glfw",
        # 网络客户端（真正的调用应该走 llm/ 或 tts/ 里的适配器）
        "requests",
        "httpx",
        "aiohttp",
        "urllib3",
        "socket",
        # 语音后端
        "edge_tts",
    }
)


@dataclass(frozen=True)
class Exemption:
    """相对 src/ 的文件或目录，以及它被允许 import 的包。"""

    relative_path: str
    allowed: frozenset[str]


EXEMPTIONS = (
    # 装配入口：将来会 import PyQt5，这是它的职责
    Exemption("main.py", FORBIDDEN_PACKAGES),
    # 界面层
    Exemption("ui", frozenset({"PyQt5", "PyQt6", "PySide2", "PySide6"})),
    # 渲染层
    Exemption("live2d", frozenset({"pygame", "live2d", "OpenGL", "glfw"})),
    # 唯一允许碰语音后端的地方
    Exemption("tts/edge_impl.py", frozenset({"edge_tts"})),
)


def _iter_source_files() -> list[Path]:
    return sorted(path for path in SRC.rglob("*.py") if path.is_file())


def _allowed_for(path: Path) -> frozenset[str]:
    relative = path.relative_to(SRC).as_posix()
    allowed: set[str] = set()
    for rule in EXEMPTIONS:
        if relative == rule.relative_path or relative.startswith(f"{rule.relative_path}/"):
            allowed |= rule.allowed
    return frozenset(allowed)


def _imported_top_levels(path: Path) -> set[str]:
    """取出一个文件里所有 import 的顶层包名（相对导入不算）。"""
    tree = ast.parse(path.read_text(encoding="utf-8"), filename=str(path))
    names: set[str] = set()
    for node in ast.walk(tree):
        if isinstance(node, ast.Import):
            names.update(alias.name.split(".")[0] for alias in node.names)
        elif isinstance(node, ast.ImportFrom) and node.level == 0 and node.module:
            names.add(node.module.split(".")[0])
    return names


def test_src_directory_is_not_empty() -> None:
    """测试自身的健全性检查：扫不到文件说明路径写错了。"""
    assert _iter_source_files(), f"{SRC} 下没有找到任何 Python 文件"


def test_exemptions_are_well_formed() -> None:
    """豁免表只应该放宽「本来就禁止」的库。

    写错包名的豁免是静默失效的（比如把 edge_tts 写成 edge-tts），
    那种错误只有在这里才看得出来。豁免表可以包含还不存在的路径
    （main.py / ui / live2d 要到后面的任务才写），所以这里不检查存在性。
    """
    unknown = sorted(
        f"{rule.relative_path}: {name}"
        for rule in EXEMPTIONS
        for name in rule.allowed - FORBIDDEN_PACKAGES
    )
    assert not unknown, f"豁免表里出现了不在禁止清单里的包名：{unknown}"

    paths = [rule.relative_path for rule in EXEMPTIONS]
    assert len(paths) == len(set(paths)), f"豁免表里有重复路径：{paths}"


def test_core_layer_does_not_import_gui_or_network_libraries() -> None:
    violations: list[str] = []
    for path in _iter_source_files():
        allowed = _allowed_for(path)
        offending = sorted(_imported_top_levels(path) & FORBIDDEN_PACKAGES - allowed)
        relative = path.relative_to(SRC).as_posix()
        violations.extend(f"{relative} 不许 import {name}" for name in offending)

    assert not violations, "层级边界被破坏：\n" + "\n".join(violations)
