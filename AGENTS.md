# AGENTS.md

> 这是给 AI 协作者看的规则文件，不是给人看的产品说明。
> 产品定位看 `docs/product.md`，接口与事件契约看 `docs/contracts.md`，术语含义看 `CONTEXT.md`。
> 动手前先读这四份。

## 项目

Agent 驱动的 Live2D 数字角色。求职作品，目标岗位 AI Agent / LLM 应用工程师。
架构思路参照 [MacchaPafe/D_sakiko](https://github.com/MacchaPafe/D_sakiko)，砍掉语音识别（ASR）。

一句话：文本输入 → LLM 流式回复 → TTS 合成语音 → Live2D 做表情和口型。

## 技术栈

- Python 3.11（钉死 3.11.x，不用 3.12+）
- PyQt5 —— 窗口与对话界面
- live2d-py + pygame + OpenGL —— Live2D 渲染，跑在独立子进程
- LiteLLM —— LLM 路由，统一多 Provider
- edge-tts —— M1 的语音合成后端（为什么选它见 `docs/adr/0001`）
- pydantic-settings —— 配置
- pytest / ruff / mypy

## 硬约束

违反其中任何一条的改动，一律退回：

1. **核心层不许 import GUI 或网络库。** `runtime.py`、`llm/`、`tts/base.py`、`emotion/` 里不允许出现 `PyQt5`、`pygame`、`edge_tts`。这是 CI 能跑、以及将来能加 Web 接口的前提（见 `docs/adr/0002`）。
2. **只有 `tts/edge_impl.py` 允许 import `edge_tts`。** 其他任何地方不许出现这个库的类型或异常。
3. **口型只用音频音量驱动**，不使用 edge-tts 的逐字时间戳（见 `docs/adr/0001`）。
4. **配置只走 `.env`**，API Key、模型名、文件路径一律不硬编码；仓库里只提交 `.env.example`。

## 目录结构

```
Live2d/
├── AGENTS.md
├── CONTEXT.md
├── README.md
├── pyproject.toml
├── .env.example
├── .gitignore
├── docs/
│   ├── product.md
│   ├── contracts.md
│   └── adr/
├── src/                      # 包根：pyproject 里声明 package-dir = {"" = "src"}
│   ├── main.py               # 桌面入口：装配 + 启动
│   ├── config.py             # 配置加载与校验
│   ├── events.py             # 统一事件定义
│   ├── runtime.py            # 会话编排（核心层）
│   ├── llm/
│   │   ├── router.py         # LiteLLM 封装，流式
│   │   └── schemas.py        # 消息等数据模型
│   ├── emotion/
│   │   ├── rules.py          # 关键词规则 → EmotionLabel
│   │   └── mapping.py        # EmotionLabel → 动作组 / 表情名
│   ├── tts/
│   │   ├── base.py           # TtsBackend 协议 + TtsChunk + TtsState
│   │   └── edge_impl.py      # 唯一允许 import edge_tts 的文件
│   ├── live2d/
│   │   └── renderer.py       # 渲染子进程入口
│   └── ui/
│       └── window.py         # PyQt5 主窗口
├── tests/
└── .github/workflows/ci.yml
```

## 常用命令

```bash
python -m venv .venv
.venv\Scripts\activate
pip install -e ".[dev]"

ruff check src tests
mypy src
pytest -q

python -m main          # 启动桌面程序（M1-6 之后才有）
```

## 编码规范

- 所有函数必须有类型注解；`ruff` 和 `mypy` 必须通过
- 每个模块必须配单元测试；LLM 与 TTS 在测试里必须 mock，不发真实网络请求
- 提交信息用 Conventional Commits（feat / fix / docs / test / chore）
- 不删除已有测试，除非用户明确要求
- 不擅自新增第三方依赖，需要时先说明理由并等确认

## Agent 协作规则

1. 每次任务开始前，先读 `AGENTS.md` + `docs/product.md` + `docs/contracts.md` + `CONTEXT.md`
2. 一次只做一个模块，不跨模块改
3. 改动前先给**文件清单和思路**，等用户确认再动手
4. 写完代码必须同时写单元测试
5. 不做技术选型，遇到选型问题先问
6. 完成后按固定格式报告：**改了什么 / 为什么 / 怎么验证**

## 代码审查规则

审查 diff 时重点看这些，格式问题交给 ruff 就行：

- 核心层有没有偷偷 import GUI 或网络库
- 有没有单方面改动 `docs/contracts.md` 定义的东西；改了契约必须先改文档
- 测试有没有被削弱：删用例、放宽断言、把真实网络调用留在测试里
- 有没有未申报的新依赖
- 音频临时文件的清理有没有遗漏
- 异常被吞掉了吗（`except: pass` 需要理由）

## 当前任务

**M1-1：搭建项目骨架 + LLM 路由层。** 任务清单见 `docs/product.md` 的「M1 任务切分」。
