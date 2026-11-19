# 运行手册

只讲怎么跑、怎么查。设计理由看 `docs/decisions.md`，接口签名看 `docs/reference.md`。

## 第一次跑起来

按顺序做完这七步，再往下走。

1. 确认 Python 是 3.11.x。`live2d-py` 只发布 cp311 的 wheel，3.12 装不上。

```bat
py -3.11 --version
```

2. 在项目根建虚拟环境。

```bat
python -m venv .venv
```

3. 装依赖。`dev` 组跑测试，`gui` 组才有窗口和渲染，两个都要。

```bat
.venv\Scripts\pip install -e ".[dev,gui]"
```

4. 复制配置模板。

```bat
copy .env.example .env
```

5. 打开 `.env`，填 `LLM_API_KEY`。用 DeepSeek 就填 DeepSeek 的 Key；换 OpenAI 兼容端点时把 `LLM_BASE_URL` 一起填上。
6. 放模型。把官方 `Hiyori` 目录整个解压到 `models/hiyori/`，确认里面能看到 `Hiyori.model3.json`。路径写目录或写 json 都认。素材从官方 Cubism Web Samples 仓库的 `Samples/Resources/Hiyori/` 取，或从官网 Sample Data 下载页取（后者要先同意 Free Material License 和该模型的 Sample Model Terms）；素材不入 git，换机器要重新放。
7. 启动。

```bat
run.bat
```

`run.bat` 会切到脚本所在目录、检查 `.venv`、缺 `.env` 时警告并用默认值、把 `src` 加进 `PYTHONPATH` 后启动程序。失败时以 `[x]` 开头并暂停，窗口不会一闪而过。

## 配置项表

只改项目根的 `.env`（程序按项目根定位，不按当前工作目录），改完重启；程序不热加载配置。

| 键 | 默认值 | 说明 | 什么时候要改 |
|---|---|---|---|
| `LLM_PROVIDER` | `deepseek` | 路由到哪家。可选 `deepseek` / `openai_compatible` | 换供应商 |
| `LLM_MODEL` | `deepseek-chat` | 模型名，原样交给 LiteLLM | 换模型或换供应商 |
| `LLM_API_KEY` | 空 | API Key。空着能启动，第一次发消息才报"配置有问题" | 必填；换 Key |
| `LLM_BASE_URL` | 空 | OpenAI 兼容端点，填到 `/v1` | `LLM_PROVIDER=openai_compatible` 时必填 |
| `LLM_TEMPERATURE` | `1.0` | 采样温度，范围 0.0–2.0 | 回复太散时调低 |
| `LLM_TIMEOUT` | `30.0` | 单次 LLM 请求超时（秒），必须大于 0 | 网络慢或长回复被掐断时调大 |
| `TTS_BACKEND` | `edge` | 语音后端。M1 只有 `edge` | 不用改 |
| `TTS_EDGE_VOICE` | `zh-CN-XiaoxiaoNeural` | edge-tts 预设音色 | 换音色；名字写错会合成失败 |
| `TTS_EDGE_RATE` | `+0%` | 语速，带符号的百分比 | 想快或慢，例如 `+10%` |
| `TTS_AUDIO_DIR` | `tmp_audio` | 临时音频目录，相对项目根 | 想换位置；退出时会清空 |
| `LIVE2D_MODEL_PATH` | `models/hiyori` | 模型目录或模型 json | 换模型或挪位置 |
| `LIVE2D_WINDOW_WIDTH` | `400` | 模型窗口宽，正整数 | 模型被裁 |
| `LIVE2D_WINDOW_HEIGHT` | `600` | 模型窗口高，正整数 | 模型被裁 |
| `LOG_LEVEL` | `INFO` | 日志级别，写错自动退回 `INFO` | 排障时改 `DEBUG` |

四个字段不能留空，空串启动就报错：`LLM_MODEL`、`TTS_EDGE_VOICE`、`LIVE2D_MODEL_PATH`、`TTS_AUDIO_DIR`。温度超出 0–2、超时小于等于 0、窗口宽高小于等于 0，同样启动就报错。

## 分两半验证

先跑渲染这一半，再跑文字与语音这一半。两个都过，问题才在界面装配。

**渲染这一半**：验证渲染子进程能不能把模型加载起来，不碰 LLM 和 TTS。

```bat
.venv\Scripts\python.exe tests\probe_renderer.py
```

期望结论 `renderer.ready`，并短暂弹出模型窗口（约 3 秒）。其他结论：`renderer.failed` = 模型加载失败但进程活着，按"无模型展示"降级；`进程退出码 N` = 渲染进程压根没起来，多半缺 pygame / live2d-py；退出码 2 = 模型路径不存在。

**文字与语音这一半**：验证 LLM → 情感 → TTS 的链路。会联网、花 API 额度。

```bat
.venv\Scripts\python.exe tests\probe_turn.py
```

期望依次看到：提问行、模型与语音行、逐字回复、`[情感] ...`、若干 `[语音]` 状态行、`[分片] 第 1/N 段 <path>`、`延迟：首字 ... / 首音 ... / 整轮 ...`、`音频分片：N 段` 与各文件大小。音频留在 `tmp_audio/`，可以直接点开听。退出码 0 = 拿到音频；1 = 跑完但没有音频；2 = 出现错误事件。

想看稳态延迟，加 `--turns 3` 连跑三轮：

```bat
.venv\Scripts\python.exe tests\probe_turn.py --turns 3
```

第一轮含 `import litellm` 的一次性开销，从第二轮起才是稳态。延迟口径与实测数据详见 `docs/decisions.md`。

**与 CI 同款的自动检查**：改完代码、冒烟之前各跑一次。

```bat
.venv\Scripts\ruff check src tests
.venv\Scripts\mypy src
.venv\Scripts\pytest -q --cov --cov-report=term-missing
```

期望三条全过。覆盖率门禁 80% 写在 `pyproject.toml` 里，本地跑也受约束。

## 冒烟清单

双击 `run.bat` 启动，逐项做，12 项全过才算可交付。

| # | 检查项 | 怎么做 | 期望 |
|---|---|---|---|
| 1 | 窗口与模型 | 启动 | 出现对话窗口；模型窗口显示角色；状态栏"空闲" |
| 2 | 待机动作 | 盯 10 秒 | 有呼吸、眨眼，不是一张死图 |
| 3 | 流式文本 | 输入"你好"回车 | 回复逐字出现；状态栏走完"正在回复…"→"合成语音…"→"播放中…"→"空闲" |
| 4 | 口型 | 边听边看嘴 | 说话时嘴随音量开合，说完闭上 |
| 5 | 语音 | 同上 | 能听到声音，音色与 `.env` 一致 |
| 6 | 打断（新消息） | 语音还在响时立刻再发一条 | 旧语音立刻停、口型归位；旧回复标"（已打断）"；新回合正常开始 |
| 7 | 打断（停止键） | 回复进行中按"停止" | 同上；输入框里已输入的内容不丢 |
| 8 | 无模型降级 | 把 `LIVE2D_MODEL_PATH` 改成不存在的路径，重启 | 窗口照常，文字与语音照常；界面报"无模型展示"，不崩 |
| 9 | 缺 Key 报错 | 清空 `LLM_API_KEY`，重启后发一条 | 状态栏"配置有问题"，写清要改 `.env`，不崩 |
| 10 | 换 Provider | 改 `LLM_PROVIDER` / `LLM_MODEL`，重启 | 仍能正常对话 |
| 11 | 临时音频清理 | 聊几轮后正常关窗 | `tmp_audio/` 变空 |
| 12 | 无残留进程 | 关窗后看任务管理器 | 没有残留的 python 进程 |

## 排障

按症状查表。表里不带命令行的地方，看表后的修复命令。

| 症状 | 可能原因 | 处理 |
|---|---|---|
| 没有声音 | edge-tts 联网失败或被限流；音色名写错；系统音量或输出设备不对；音频分片没生成 | 先跑第 3 节的文字与语音探针。有 `[分片]` 落盘但听不到，查系统音量与输出设备；没有分片，查网络，把 `TTS_EDGE_VOICE` 换回默认值重试。 |
| 无模型展示 / 模型窗口空白 | 模型路径不对；目录里没有模型 json；目录里有多个模型；缺 `gui` 依赖 | 先跑第 3 节的渲染探针看结论。按第 1 节第 6 步重放素材；确认目录里恰好一个 `*.model3.json`；补装 GUI 依赖（修复命令 1）。 |
| 状态栏"配置有问题" | `LLM_API_KEY` 为空；`openai_compatible` 没填 `LLM_BASE_URL`；必填字段留空；数值越界 | 按报错文字改 `.env` 再重启。四个必填项不能空；温度 0–2；超时大于 0。 |
| 模型加载失败（探针报 `renderer.failed`） | 素材不完整，缺 moc3 或贴图；路径含中文或空格；Python 不是 3.11 | 用官方完整目录覆盖 `models/hiyori/`；把项目和模型移到纯英文、无空格路径；确认 Python 是 3.11.x。 |
| 窗口关不掉 / 残留 python 进程 | 渲染子进程没退出；上次异常退出留了进程 | 正常关窗会等渲染进程最多 3 秒，先等一等。仍不消失就结束残留进程（修复命令 2）。 |
| 关窗后 `tmp_audio/` 还有文件 | 程序异常退出，没走到清理；文件被占用 | 正常关窗会清空。异常退出的残留手动删（修复命令 3）；删不掉先关掉占用它的播放器。 |
| 首字、首音很慢 | 第一轮含 `import litellm` 开销；网络抖动；edge-tts 握手慢 | 用 `--turns 3` 看第二轮起的稳态。冷启动那一轮慢是已知现象，不是故障。 |
| 装不上 `live2d-py` | Python 3.12 以上；不是 Windows | 用 Python 3.11 重建 venv，再重装。 |
| 程序一闪而过 / 提示找不到 `.venv` | 没建虚拟环境；`.venv` 被删 | 按第 1 节重建环境。`run.bat` 会切到自身目录，从哪双击都行。 |
| LLM 报鉴权失败、限流或额度不足 | Key 错或过期；Provider 与 Key 不配套；余额不足；429 限流 | 核对 `LLM_API_KEY` 与 `LLM_PROVIDER` 是否同源；换 Key 后重启；限流等几分钟重试。 |

修复命令 1，补装 GUI 依赖：

```bat
.venv\Scripts\pip install -e ".[gui]"
```

修复命令 2，查残留进程并结束：

```bat
tasklist | findstr /i "python"
taskkill /F /IM python.exe
```

第二行会结束本机所有 python 进程，先确认没有别的程序在跑。

修复命令 3，清临时音频：

```bat
del /q tmp_audio\*
```

## 已知限制

先接受下面这些，遇到别当故障查。

- **免费素材看不出情感差异**：官方 `Hiyori` 只有 `Idle` 和 `TapBody` 两个动作组，没有表情文件，任何情感都回落待机动作。US-3 的"按情感切换表情或动作"用这份素材验不了；要验就换带情感动作组的模型，或加"情感 → 面部参数"的直接映射。
- **CI 覆盖不到界面与渲染**：`ui/window.py` 和 `stage/renderer.py` 必须保持薄壳，逻辑放在 `ui/state.py` 和 `stage/` 的其他模块里，那些才测得到。
- **音色固定**：edge-tts 只能挑预设音色，不能克隆。
- **首音延迟偏高**：M1 等整段回复合成完才播，不是边流边合成。
- **模型素材不入库**：`.gitignore` 排除了 `models/`，换机器要重新放。
- **语音走在线服务**：不承诺数据不出本机，敏感内容不要输入。
- **只保证 Windows**：M1 不承诺跨平台，也不承诺音质。
