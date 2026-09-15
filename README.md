# Live2D 数字角色

Agent 驱动的 Live2D 数字角色：文本输入 → LLM 流式回复 → TTS 合成语音 → Live2D 表情与口型。

求职作品，目标岗位 AI Agent / LLM 应用工程师。目前处于 M1 的文档阶段，还没有代码。

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
