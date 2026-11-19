# 架构与时序

这份文档回答"系统怎么动起来"：一次对话按什么顺序发生、每件事归谁管、失败时退到哪里。
**接口签名不在这里**——查签名去 [`reference.md`](reference.md)；**为什么这么设计**去 [`decisions.md`](decisions.md)。

## 0. 用词

代码、提交信息、issue 里都用这一列的说法。术语只在真正会混的地方列。

| 词 | 含义 | 不要叫 |
|---|---|---|
| **契约** | 被两个及以上模块 import、或跨进程传的东西，定义在 `src/contracts/` | 接口层、公共模块 |
| **端口** | 契约里那些 `Protocol`：实现方必须满足的方法集合 | 抽象类、interface |
| **回合** | 用户发一条消息，到 runtime 发完 `turn.done` 为止的编排过程，由 `turn_id` 标识 | 一次请求、一轮对话 |
| **播放阶段** | `turn.done` 之后，渲染进程把该回合已派发的音频播完的过程。沿用原 `turn_id`，但不是新回合 | 第二回合 |
| **分片** | 一段可独立播放的音频，对应回复里的一句话 | 音频块、chunk |
| **呈现通道** | runtime 眼里的"声音和表情往哪送"，只有 `play` / `set_emotion` / `stop` 三个方法 | 播放器、renderer |
| **舞台层** | `src/stage/`，主进程侧那一半。不叫 live2d，因为第三方库的顶层模块就叫 `live2d` | 渲染层、live2d 包 |
| **渲染进程** | 单独跑 pygame + OpenGL + live2d-py 的子进程 | Live2D 窗口、渲染线程 |
| **合成中** | TTS 状态之一，界面从第一天就要能显示 | loading |
| **打断** | 取消当前编排回合或正在进行的播放 | 取消请求、abort |
| **音色档案** | 描述"用什么音色说话"的配置对象 | voice、TTS 参数 |

## 1. 一分钟版

```
用户输入 → ui/window.py ──信号──▶ main.py（装配）──▶ runtime.py
                                                        │
                                                        ├─▶ RendererControl → stage/channel.py ──▶ 渲染子进程
                                                        ├─▶ TtsBackend      → tts/edge_impl.py
                                                        └─▶ LlmClient       → llm/router.py

渲染子进程 stage/renderer.py：pygame 放音频 ─ 音量驱动口型 ─ live2d 画脸
两条队列只传普通字典，不传对象。
```

三句话：

1. **主进程负责想和说**：调 LLM、切句、合成音频、决定表情。它是唯一碰网络的地方。
2. **渲染子进程负责演**：放音频、算口型、画脸。它也是唯一知道"现在到底有没有声音"的地方。
3. **两边只通过两条队列说话**，内容是普通字典——将来换成 WebSocket，协议不用重新设计。

## 2. 一次对话的时序

下面每一步都标了**发出什么事件**或**发出什么命令**。取消检查点用 ⛔ 标出。

### 2.1 正常回合

```
① 用户按回车
   window._emit_input → user_submitted(str) 信号 → main.on_submitted
   SendQueue.submit(text, active_turn_id=None) → start_now=text

② main.run_turn 起一个后台线程 → runtime.send(text)
   校验非空；已有回合在跑则抛 RuntimeError（不并发、不隐式取消）

③ runtime 分配 turn_id，置 _active
   ⇒ turn.start(user_text)
   user 消息进历史

④ runtime._stream_reply
   settings.require_llm_credentials()      ← 缺 Key 在这里失败
   LlmClient.stream(...) 是惰性生成器：第一次迭代才发请求
   每收到一段增量：
     ⛔ 检查取消标志
     ⇒ llm.token(text)

⑤ 流结束
   ⇒ llm.done(finish_reason="stop")
   assistant 消息进历史（中途取消的半个回复走不到这里）

⑥ detect(reply) → EmotionLabel
   ⇒ emotion.detected(label, source="rules")
   → RendererControl.set_emotion()  → 命令 set_emotion

⑦ split_sentences(reply) 切句，得到 N 句
   ⇒ tts.state(synthesizing)
   对第 i 句：
     ⛔ 检查取消标志
     TtsBackend.synthesize(句子, 序号=i, 总数=N)   ← 阻塞，等网络
     对产出的每一片：
       ⛔ 检查取消标志
       ⇒ tts.chunk(segment_index, segment_total, path, format)
       → RendererControl.play()  → 命令 play_audio

⑧ 全部派发完毕
   ⇒ turn.done
   _active 置回 None
```

**`turn.done` 不代表播完。** `send()` 跑在后台线程里，如果要等语音播完才返回，那个线程会被占好几秒，界面什么都做不了。所以它派发完就返回，播放归渲染进程。

### 2.2 播放阶段（`turn.done` 之后）

```
渲染进程收到 play_audio → PlaybackPlanner 排队
  空闲时：pygame.mixer.Sound(...).play()
         ⇒ 回传 audio.started(turn_id, segment_index)
主进程 QTimer 每 100ms 轮询回传队列
  ⇒ 翻译成 tts.state(playing)
这一片播完：
  队列还有 → 直接播下一片
  队列空了 → 回传 audio.idle
           ⇒ tts.state(idle)
```

`playing` / `idle` 可能在 `turn.done` 之后到达，但**沿用原 `turn_id`**。接收方不能因为见过 `turn.done` 就丢掉播放状态。

### 2.3 编排中被取消

```
用户又发了一条（或按停止）
  SendQueue.submit(text, active_turn_id="abc") → cancel_turn_id="abc"
  runtime.cancel("abc", reason="user_new_message")
      ├ 置取消标志（不阻塞）
      ├ TtsBackend.cancel("abc")
      └ RendererControl.stop("abc") → 命令 stop_audio

回合线程在下一个 ⛔ 看到标志 → 抛内部异常 → 统一收尾
  ⇒ turn.cancelled(reason)
  _active 置回 None
  ⇒ 此后不再产生该 turn_id 的任何编排事件

渲染进程收到 stop_audio
  → 停当前播放、口型归位、丢弃同回合待播分片
  → 如果当时确实有音频在播，回传 audio.idle → tts.state(idle)
    （只是队列里有待播、当前没在播时，不会有回传）
```

**取消是硬约束**：发出 `turn.cancelled` 之后，属于这个 `turn_id` 的后续编排事件一律丢弃，不许漏出半句。

### 2.4 失败

```
LLMError       ⇒ error(code) ⇒ turn.cancelled(reason="error")
TtsError       ⇒ tts.state(failed, detail) ⇒ error(tts_error) ⇒ turn.cancelled(reason="error")
配置不完整      ⇒ error(invalid_request) ⇒ turn.cancelled(reason="error")
其他 Exception  ⇒ 记 traceback ⇒ error(internal_error) ⇒ turn.cancelled(reason="error")
```

出错用 `turn.cancelled(reason="error")` 收尾，**不用** `turn.done`。界面靠这个区分"正常结束"和"出事了"。

## 3. 边界与所有权

### 3.1 谁在哪跑

| 东西 | 在哪 | 谁拥有 |
|---|---|---|
| LLM 调用 | 主进程的回合线程 | runtime |
| TTS 合成 | 主进程的回合线程（没有单独开子进程） | runtime 调用的 `TtsBackend` |
| 音频文件 | 磁盘上的 `TTS_AUDIO_DIR` | TTS 后端写，渲染进程读，main 在退出时清 |
| 播放 | 渲染子进程 | 渲染进程 |
| 口型 | 渲染子进程 | 渲染进程 |
| 界面 | 主进程的界面线程 | `ChatWindow` |

### 3.2 线程规则

- `ChatRuntime.send()` **阻塞到编排结束**，返回本回合的 `turn_id`。界面装配层负责把它放进后台线程；runtime 不创建、不 join 线程。
- `EventSink` 可能从回合线程或界面线程被调用。sink 实现必须自己保证跨线程投递安全；桌面壳用 Qt 信号的排队连接。
- `cancel()` **不阻塞**，只设标志。

### 3.3 依赖方向

```
                contracts/（端口、事件、数据类型、异常）
                   ▲        ▲        ▲        ▲
                   │        │        │        │
                 llm/     tts/     stage/    ui/
                   ▲        ▲        ▲        ▲
                   └────────┴────┬───┴────────┘
                              runtime.py
                                  ▲
                                main.py
```

规则只有一条：**箭头只能朝上**。`contracts/` 只 import 标准库；实现层 import 契约；`runtime` 不认识具体实现，只认识端口。

例外只有三个，由 `tests/test_layer_boundaries.py` 用 AST 强制执行，新增文件自动被覆盖：

| 文件 | 放行的库 |
|---|---|
| `main.py`、`ui/` | GUI 包（PyQt5 等） |
| `stage/renderer.py` | `pygame` / `live2d` / `OpenGL` / `glfw` |
| `tts/edge_impl.py` | `edge_tts` |

### 3.4 音频的清理

- 文件名：`{turn_id}-{segment_index}.mp3`，落在 `TTS_AUDIO_DIR`。
- 合成失败或取消时，后端删掉没交付的半成品；**已交付的不删**（渲染进程可能正在播）。
- 退出时 `main._cleanup_audio_dir()` 清空整个目录，删不掉的只记日志，不挡退出。

## 4. 失败与降级

用户视角的一览表。写测试和做冒烟时按这张表核对。

| 场景 | 用户看到什么 | 程序状态 |
|---|---|---|
| 没填 `LLM_API_KEY` | 状态栏"配置有问题"，说明要改 `.env` | 窗口正常，可以继续操作 |
| LLM 超时 | "模型超时" | 回合终止，可以重发 |
| LLM 报错 | "模型出错" | 同上 |
| 语音合成失败 | "语音失败" + 具体原因 | 文字照常显示，只是没声音 |
| 模型加载失败 | "无模型展示" | 窗口、文字、语音全部照常 |
| 渲染进程完全没起来 | "无模型展示"，提示缺 GUI 依赖 | 同上，启动 2 秒后检测 |
| 队列里收到坏消息 | 无感知 | 记一条 warning 就丢掉，不影响界面 |
| 用户按停止 | "已打断"，回复标"（已打断）" | 编排终止，已发出的文字保留 |
| 新消息打断旧的 | 同上 | 旧回合终止，新回合在旧回合收尾后开始 |

贯穿的一条原则：**渲染和语音都是可选的表现能力**。它们失败时，文本对话必须照常可用。

## 5. 扩展点

### 5.1 换 LLM Provider

改 `.env` 两行，不用动代码：

```dotenv
LLM_PROVIDER=openai_compatible
LLM_MODEL=Qwen/Qwen2.5-7B
LLM_BASE_URL=https://api.example.com/v1
```

模型名前缀由 `normalize_model_name()` 统一处理，规则见表：`deepseek-chat` → `deepseek/deepseek-chat`；已带已知前缀的原样使用；`openai_compatible` 下未识别的名字统一补 `openai/`。**厂商命名空间（`Qwen/`、`deepseek-ai/`）长得像 provider 前缀，这是唯一容易踩的坑。**

### 5.2 换 TTS 后端

三步：实现 `TtsBackend` 协议 → 在 `create_tts_backend()` 里登记后端名 → 在 `config.py` 的 `TTSBackendName` 加上这个名字。上层（runtime、界面、事件）**一行都不用改**。

### 5.3 以后挂工具（Agent 方向，尚未实现）

这一节描述设计方向，代码里还没有。写在这里是为了固定接缝。

- **循环位置**：`runtime._run_turn()` 现在是线性的（LLM → 情感 → TTS）。接工具就是把它改成循环：调模型 → 有 tool_calls 就执行 → 把结果塞回消息 → 再调。上层接口不变。
- **事件**：需要新增 `agent.step` / `tool.call` / `tool.result`。现有 `Event` 基类的形状（`type` + `turn_id` + `to_frame()`）够用，不用改。
- **冲突要提前想**：工具调用轮没有文本增量，会打断"逐字流式"的体验；并且工具轮不能合成语音，所以"边流边合成"必须排在工具之后。

### 5.4 换成 Web 形态

事件 → WebSocket 帧：`{"type": …, "turn_id": …, "data": {…}}`，一对一，因为事件本来就是数据结构。
呈现通道 → 新实现：把 `RendererControl` 实现成"往 WebSocket 发帧"，runtime 一行不用改。
需要新增：连接鉴权、音频文件服务端点、断线重连后的状态同步。

## 6. 已知缺口

**这一节列的是"已知没做到"，不是契约允许。** 修复时不要把它当成设计要求来兼容。

| # | 缺口 | 表现 |
|---|---|---|
| 1 | 播放阶段打断未闭环 | `turn.done` 之后按停止没反应（此时停止键是禁用的）；此时发新消息，旧语音继续播，新回合音频排在它后面 |
| 2 | 下一回合启动有竞态 | `turn.done` / `turn.cancelled` 在旧 `send()` 返回**之前**发出；挂起的待发消息可能撞上"上一回合还没结束"，被吞掉 |
| 3 | 取消与派发之间的小窗口 | 取消恰好发生在"检查标志"与"发出 play 命令"之间时，该分片仍会被播放 |
| 4 | 取消集合只增不减 | `EdgeTtsBackend._cancelled` 每个回合加一个 id，从不清理 |
| 5 | 渲染进程只检查一次 | 启动 2 秒后检查一次是否活着；之后崩掉无人知晓，表现为突然没声音也没画面 |

第 1、2 条是**用户能感知的功能问题**，其余是结构债。
