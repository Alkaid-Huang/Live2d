# AGENTS.md

给 AI 协作者的工程约定。产品说明看 [README.md](README.md)，接口看 [docs/reference.md](docs/reference.md)，时序与边界看 [docs/architecture.md](docs/architecture.md)。

## 一句话

文本输入 → LLM 流式回复 → TTS → Live2D 表情与口型。

## 硬约束

1. `src/contracts/` 只 import 标准库；实现层只依赖契约，依赖方向永远指向契约。
2. 核心层（`runtime.py`、`llm/`、`tts/base.py`、`emotion/`、`stage/` 的非渲染部分）不许 import `PyQt5` / `pygame` / `live2d` / `edge_tts`。
3. 只有 `tts/edge_impl.py` 允许 import `edge_tts`。
4. 口型只用音频音量驱动，不用逐字时间戳。
5. 配置只走 `.env`，不硬编码；仓库只提交 `.env.example`。

放行例外（由 `tests/test_layer_boundaries.py` 用 AST 强制，新增文件自动覆盖）：`main.py` 与 `ui/` 可用 GUI 包；`stage/renderer.py` 可用 `pygame` / `live2d` / `OpenGL` / `glfw`。

## 命令

```bat
ruff check src tests
mypy src
pytest -q --cov
mkdocs build                       # 接口文档，需要 pip install -e ".[docs]"
python -m main                     # 启动桌面程序
```

## 编码规范

- 所有函数有类型注解；`ruff` 与 `mypy` 必须通过。
- 每个模块配单元测试；测试里 LLM 与 TTS 必须替换成替身，不发真实网络请求。
- **docstring 就是接口文档**：一个符号一条，结构固定为「一句话 / Args / Raises / Example」，由 mkdocs 生成到 `docs/reference.md`。加接口先写 docstring。
- 提交信息用 Conventional Commits（feat / fix / docs / test / chore）。
- `.bat` 只写 ASCII 且必须是 CRLF。
- 不擅自新增第三方依赖；不删除已有测试，除非用户明确要求。

## 协作规则

1. 动手前先读 README、`docs/architecture.md`、`docs/reference.md`。
2. 一次只改一个模块；改动前给文件清单和思路，等确认。
3. 改接口等于改两端：先改代码与 docstring，再 `mkdocs build` 确认页面没坏。
4. 完成后按固定格式报告：**改了什么 / 为什么 / 怎么验证**。

## 审查重点

- 核心层有没有偷偷 import GUI、网络库或具体后端。
- 有没有单方面改事件形状、事件顺序或取消语义；改了必须先改 `docs/architecture.md` 第 2 节。
- 测试有没有被削弱：删用例、放宽断言、把真实网络调用留在测试里。
- 音频临时文件的清理有没有遗漏。
- 异常被吞掉了吗（`except: pass` 需要理由）。
- 新增符号有没有进 `contracts/__init__.py` 的 `__all__` 和 `docs/reference.md`。
