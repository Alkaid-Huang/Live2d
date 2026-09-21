# Live2D 数字角色

Agent 驱动的 Live2D 数字角色：文本输入 → LLM 流式回复 → TTS 合成语音 → Live2D 表情与口型。

求职作品，目标岗位 AI Agent / LLM 应用工程师。M1-6 已完成：桌面形态的整条链路装配完毕，
可以在本机跑起来。

## 跑起来

```bat
python -m venv .venv
.venv\Scripts\pip install -e ".[dev,gui]"
copy .env.example .env
rem 打开 .env，填 LLM_API_KEY

rem 模型素材不入库，按 docs/product.md 的「技术风险」放到 models/hiyori/

run.bat
```

`run.bat` 就是"一键启动"——本机脚本，不是容器（理由见 ADR 0002）。
想单独验证渲染这一半：`.venv\Scripts\python.exe tests\probe_renderer.py`。

完整的人工检查清单在 [docs/smoke-test.md](docs/smoke-test.md)。

## 目录

| 路径 | 是什么 |
|---|---|
| `src/llm/` | LLM 路由（LiteLLM 封装） |
| `src/tts/` | 语音合成，后端可替换（M1 是 edge-tts） |
| `src/emotion/` | 关键词规则 → 情感标签 → 动作组/表情名 |
| `src/runtime.py` | 回合编排（核心层，不碰界面） |
| `src/stage/` | 舞台层：渲染子进程，以及它的协议、口型、待播队列 |
| `src/ui/` + `src/main.py` | 桌面窗口与装配入口 |

## 文档导航

| 文件 | 作用 |
|---|---|
| [AGENTS.md](AGENTS.md) | 给 AI 协作者的项目规则与硬约束 |
| [CONTEXT.md](CONTEXT.md) | 术语表：文档和代码里这些词的确切含义 |
| [docs/product.md](docs/product.md) | 做什么、不做什么、验收标准、任务切分、风险 |
| [docs/contracts.md](docs/contracts.md) | 模块接口与事件契约（改这里等于改两端） |
| [docs/adr/](docs/adr/) | 决策记录：为什么这么做、代价是什么、什么时候改 |

## 技术栈

Python 3.11 · PyQt5 · live2d-py · LiteLLM · edge-tts · pytest + ruff + mypy

## 路线图

- **M1 闭环**：文本 → LLM → TTS → Live2D，一家到两家 LLM Provider
- **M2 表现力**：情感换成分类模型、多角色、会话持久化
- **M3 能力**：ReAct 工具调用 + RAG 知识库
- **M4 材料**：性能数据、演示与答辩

## 参照

架构思路参照 [D_sakiko](https://github.com/MacchaPafe/D_sakiko)，差异见 [docs/product.md](docs/product.md)。
