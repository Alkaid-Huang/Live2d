# Live2D 数字角色

一个跑在本机的 Live2D 数字角色：你打字，它用大模型回复，用语音说出来，脸上有表情、嘴跟着声音动。

求职作品，目标岗位 AI Agent / LLM 应用工程师。重点不在"会做 Live2D"，而在**能划清多模块边界、能接多家 LLM、能把流式链路编排正确、并且让这一切可测试**。

## 它长什么样

```
用户输入 → ui/window.py ──信号──▶ main.py（装配）──▶ runtime.py
                                                        │
                                                        ├─▶ RendererControl → 渲染子进程（播放 + 口型 + 画脸）
                                                        ├─▶ TtsBackend      → edge-tts
                                                        └─▶ LlmClient       → LiteLLM
```

三句话：**主进程负责想和说，渲染子进程负责演，两边只通过两条队列传普通字典。**

- 端口（接口）全部集中在 `src/contracts/`，实现层只依赖契约，依赖方向永远指向契约。
- LLM 与 TTS 在测试里全部被替换，CI 不联网也能跑完 189 个测试。
- 渲染进程挂掉时自动降级成"无模型展示"，文字与语音照常。

## 五分钟跑起来

```bat
python -m venv .venv
.venv\Scripts\pip install -e ".[dev,gui]"
copy .env.example .env
rem 打开 .env，填 LLM_API_KEY
```

模型素材不进仓库（体积大、授权受限），按 [`docs/runbook.md`](docs/runbook.md) 的说明放到 `models/hiyori/`。

```bat
run.bat
```

`run.bat` 就是"一键启动"——本机脚本，不是容器。

## 文档怎么读

这份文档是按用途拆开的，别从头读到尾：

| 你想干什么 | 读哪份 |
|---|---|
| 跑起来、配环境、出问题怎么查 | [`docs/runbook.md`](docs/runbook.md) |
| 查接口签名、字段、错误码 | [`docs/reference.md`](docs/reference.md)（从 docstring 生成） |
| 搞懂一次对话按什么顺序发生、谁拥有什么 | [`docs/architecture.md`](docs/architecture.md) |
| 知道为什么这么设计、代价是什么 | [`docs/decisions.md`](docs/decisions.md) |
| 想让 AI 协作者继续写这个项目 | [`AGENTS.md`](AGENTS.md) |

生成接口参考需要额外的依赖：

```bat
.venv\Scripts\pip install -e ".[docs]"
.venv\Scripts\python -m mkdocs serve
```

## 目录

| 路径 | 是什么 |
|---|---|
| `src/contracts/` | 端口、事件、数据类型、异常。只依赖标准库 |
| `src/runtime.py` | 回合编排（核心层，不碰界面） |
| `src/llm/` | LiteLLM 封装，流式 |
| `src/tts/` | 语音合成，后端可替换 |
| `src/emotion/` | 关键词规则 → 情感标签 → 动作组/表情名 |
| `src/stage/` | 舞台层：渲染子进程与它的协议、口型、待播队列 |
| `src/ui/` + `src/main.py` | 桌面窗口与装配入口 |
| `docs/` | 四份文档，见上表 |

## 技术栈

Python 3.11 · PyQt5 · live2d-py · LiteLLM · edge-tts · pytest / ruff / mypy · mkdocs

Python 版本钉在 3.11：`live2d-py` 只发布 `cp311` 的 wheel，不是 abi3。

## 已知局限

- **免费素材看不出情感差异**：官方样例 `Hiyori` 只有 `Idle` 与 `TapBody` 两个动作组，没有表情文件，所以任何情感都会回落到待机动作。换一个带情感动作组的模型即可。
- **语音走微软的在线服务**：不承诺"数据不出本机"，不承诺音质与离线可用。
- **只保证 Windows**：渲染依赖 live2d-py 的 Windows wheel。

完整清单见 [`docs/runbook.md`](docs/runbook.md) 的「已知限制」。

## 路线图

- **M1 闭环（已完成）**：文本 → LLM → TTS → Live2D 表现，两家 LLM Provider
- **M2 表现力与延迟**：边流边合成、启动预热、情感换分类模型
- **M3 能力**：ReAct 工具调用 + RAG
- **M4 材料**：性能数据、演示与答辩

M3 会改动 `runtime` 的核心循环：现在它是线性的（LLM → 情感 → TTS），接工具要改成"调模型 → 执行工具 → 再调"。接缝位置见 [`docs/architecture.md`](docs/architecture.md) 第 5.3 节。

## 参照

架构思路参照 [D_sakiko](https://github.com/MacchaPafe/D_sakiko)，差异与取舍见 [`docs/decisions.md`](docs/decisions.md)。
