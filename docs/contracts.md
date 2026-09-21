# 接口与事件契约

M1 没有 HTTP 接口。这份文件冻结的是**模块之间怎么说话**：事件格式、事件顺序、取消语义、各模块的边界。

**改这里等于改两端，必须先改文档再改代码。**

## 1. 进程与模块边界

**主进程（桌面壳）**

| 模块 | 职责 |
|---|---|
| `ui/` | 窗口、输入框、对话显示、状态提示 |
| `runtime.py` | 会话编排：什么时候调 LLM、什么时候调 TTS、什么时候取消 |
| `llm/` | LLM 调用（LiteLLM 封装，流式） |
| `emotion/` | 情感判断与映射（输出抽象名字，不碰渲染库） |
| `tts/` | 语音合成（M1 跑在主进程的后台线程里） |

**渲染子进程**：`stage/renderer.py`，加载模型、播放音频、渲染画面。

**舞台层**（`src/stage/`）是主进程侧的那一半：`channel.py` 负责收发，`protocol.py` 定义消息，`playback.py` 管待播队列，`lipsync.py` 算口型，`cues.py` 挑动作，`model_files.py` 找模型。它叫 `stage` 而不是 `live2d`，因为第三方库 live2d-py 的顶层模块就叫 `live2d`，同名会在 `import live2d.v3` 时导到自己身上。

三个决定要说清楚：

- **音频播放放在渲染进程**，不放主进程。因为口型要用正在播放的那段音频的音量，同一个进程里最省事。
- **TTS 在 M1 跑在主进程的后台线程里**（edge-tts 是网络流，没有本地模型加载，不需要单独开进程）。将来换成本地模型时把它整体挪进子进程，**上层不用改**——这就是接口抽象的目的。
- **两个进程之间是双向的**：主进程发命令（播音频、换表情、停播放、退出），渲染进程回传状态（就绪、失败、开始播、播完）。回传存在的理由有两个：`tts.state` 的 `playing` / `idle` 只有渲染进程知道，而 `live2d_load_failed` 也只能由它上报。

runtime 不认识队列，也不认识 pygame：它只依赖 `runtime.RendererControl` 的三个方法（`play` / `set_emotion` / `stop`），实现是 `stage/channel.py`。要不要接渲染进程是装配时决定的——不传就不会有声音，文本照常（单元测试就是这么跑的）。

## 2. 统一事件

跨进程、跨界面只传一种东西：`Event`，定义在 `src/events.py`。都是 dataclass，都带 `type` 和 `turn_id`。

| type | 字段 | 谁发 | 谁收 | 含义 |
|---|---|---|---|---|
| `turn.start` | `user_text` | runtime | 界面 | 新回合开始 |
| `llm.token` | `text` | llm | 界面 | 一段增量文本 |
| `llm.done` | `finish_reason` | llm | runtime、界面 | 回复生成完毕 |
| `emotion.detected` | `label`, `source` | emotion | 界面、渲染进程 | 本回合的情感 |
| `tts.state` | `state`, `detail` | tts / 渲染进程 | 界面 | 合成/播放状态变化 |
| `tts.chunk` | `segment_index`, `segment_total`, `path`, `format` | tts | 渲染进程 | 一段音频就绪 |
| `turn.cancelled` | `reason` | runtime | 界面、渲染进程、tts | 本回合作废 |
| `turn.done` | — | runtime | 全部 | 本回合彻底结束 |
| `error` | `code`, `message` | 任意模块 | 界面 | 出错 |

`tts.state` 的取值：`idle` / `synthesizing` / `playing` / `failed`。

**界面从第一天就要显示 `synthesizing`**，不能假设语音是瞬间出来的。将来换成本地模型，第一次出声可能要等几十秒，加载提示是必需品不是装饰。

其中 `synthesizing` / `failed` 由 runtime 发（它知道合成这件事），`playing` / `idle` 由渲染进程回传后翻译而来（只有它知道音频在不在响）。**`turn_id` 为空串表示这条事件不属于任何回合**——目前只有启动期的错误会这样（比如模型加载失败），此时回合还没开始。

## 3. 事件顺序

一次正常回合：

```
turn.start
llm.token × N          逐字推给界面
llm.done
emotion.detected       回复生成完才能判断情感（M1 用关键词规则）
tts.state(synthesizing)
tts.chunk(0/N)、tts.chunk(1/N) …        逐片交给渲染进程
turn.done              主进程这一回合结束
   ↓ 之后的事由渲染进程继续，时间上一定晚于 turn.done
tts.state(playing) → … → tts.state(idle)   播完最后一片才回到 idle
```

**`turn.done` 不等播放结束**，这是有意的：`send()` 由界面层放在工作线程里跑，如果它要等语音播完才返回，那个线程会被占用好几秒，而这段时间界面什么都不能做。参照项目也是这个处理方式——主进程派发完就继续，播放归渲染子进程管。

代价是"打断"分成两半，装配时必须都接上：runtime 负责停合成（`tts.cancel`）与停播放（`RendererControl.stop`），界面层负责把新输入送进 runtime。M1-6 装配时如果只接了前一半，表现就是"新消息来了，文本停了但旧语音还在响"。

被取消的回合：

```
turn.cancelled(reason)
  ↓  之后不再产生该 turn_id 的任何事件
  渲染进程立刻停止播放、口型归位（含丢掉队列里同回合的后续分片）
```

`reason` 取值：`user_new_message`（用户又发了一条）/ `user_stop`（手动停止）/ `error`。

**取消是硬约束**：`turn.cancelled` 之后，属于这个 `turn_id` 的事件一律丢弃，不许漏出半句。

## 4. 模块接口（M1 冻结的部分）

### LLM

```python
def stream_reply(messages: list[Message], model: str, **opts) -> Iterator[str]
```

- 产出纯文本增量，不带任何 Provider 特有字段
- 拼 prompt、管上下文是 runtime 的事，不是 router 的事
- 测试必须 mock，不发真实请求

### TTS

```python
class TtsBackend(Protocol):
    def synthesize(
        self,
        text: str,
        voice: VoiceProfile,
        *,
        turn_id: str,
        segment_index: int,
        segment_total: int,
    ) -> Iterator[TtsChunk]: ...
    def cancel(self, turn_id: str) -> None: ...
```

- `text` 是**已经切好的一句话**，后端只负责合成这一句
- `segment_index` / `segment_total` 由调用方（runtime）传入并原样回填到分片里——序号是切句者的信息，不是后端的信息
- 产出 `TtsChunk`：`path` / `format` / `segment_index` / `segment_total`。**没有 `duration_ms`**：它现在没有消费者，而且两个后端无法以同等代价提供它，符合 ADR 0001 的原则
- `cancel(turn_id)` 只设置取消标志；`synthesize()` 在产出下一个分片前检查，已取消就安静停止（不抛异常），并清理尚未交付的半成品文件。已交付的分片不删，因为渲染进程可能正在播放
- 上层只认识 `TtsBackend`，不认识 `edge_tts`
- 测试用假后端，不发真实网络请求

### 音色档案

```python
VoiceProfile = {"backend": "edge" | "local", "params": {...}}
```

- `edge`：`voice`、`rate`
- `local`（预留，M1 不实现）：`model_path`、`ref_audio`、`ref_text`、`language`

两边的参数结构完全不同，所以各自待在自己的段落里，**不拍平成公共字段**。

### 情感

```python
def detect(text: str) -> EmotionLabel

EMOTION_MAPPING: dict[EmotionLabel, EmotionCue]   # → 动作组名 / 表情名
```

- `EmotionLabel`：`开心` / `难过` / `生气` / `惊讶` / `害怕` / `厌恶` / `中性`
- 映射表只输出**抽象名字**（`happiness`、`smile`），不输出 live2d-py 的参数名——这样它不依赖渲染库就能测
- **未映射的标签回落到 `中性` 并记一条日志**，不许静默失败

### 渲染进程

runtime 只依赖 `runtime.RendererControl` 的三个方法，不认识队列：

| 方法 | 作用 |
|---|---|
| `play(turn_id, segment_index, segment_total, path, format)` | 播一段音频 |
| `set_emotion(turn_id, label)` | 换表情与动作 |
| `stop(turn_id)` | 立刻停止播放、口型归位；`turn_id` 为空串表示全停 |

桌面形态的实现是 `stage/channel.py`，它把方法翻译成队列里的字典命令：

| 命令（主进程 → 渲染进程） | 字段 | 作用 |
|---|---|---|
| `play_audio` | turn_id / segment_index / segment_total / path / format | 播一段音频 |
| `set_emotion` | turn_id / label | 换表情并按情感播动作 |
| `stop_audio` | turn_id | 立刻停播、口型归位，并丢掉队列里同回合的分片 |
| `quit` | — | 退出渲染子进程 |
| `switch_model` | — | 换模型——**预留，M1 不实现** |

反向的回传（渲染进程 → 主进程），由 `message_to_events()` 翻译成事件：

| 回传 | 字段 | 翻译成 |
|---|---|---|
| `renderer.ready` | model_path | 没有事件，只是"窗口起来了"的运维信号 |
| `renderer.failed` | code / message | `error`（`turn_id` 为空串） |
| `audio.started` | turn_id / segment_index | `tts.state(playing)` |
| `audio.idle` | turn_id | `tts.state(idle)` |

两条容错约定：队列里出现无法解析的东西时**只记日志并丢弃**，不能让界面因为一条坏消息崩掉；模型加载失败时渲染进程**不退出**，退化成无模型展示，只回一条 `renderer.failed`。

## 5. 错误码

| code | 含义 |
|---|---|
| `llm_timeout` | LLM 请求超时 |
| `llm_error` | LLM 返回错误 |
| `tts_error` | 语音合成失败 |
| `live2d_load_failed` | Live2D 起不来或模型加载失败——界面退化成无模型展示（窗口还在、文字照常），不许直接崩 |
| `invalid_request` | 参数不合法 |
| `cancelled` | 被取消（不是错误，但走同一条事件通道） |

## 6. 配置项

配置分三段：LLM、TTS、Live2D。**后端专属参数带后端前缀**，见 `.env.example`。

```
LLM_PROVIDER=deepseek          # deepseek | openai_compatible
LLM_MODEL=deepseek-chat
LLM_API_KEY=
LLM_BASE_URL=
LLM_TEMPERATURE=1.0

TTS_BACKEND=edge
TTS_EDGE_VOICE=zh-CN-XiaoxiaoNeural
TTS_EDGE_RATE=+0%
TTS_AUDIO_DIR=tmp_audio

LIVE2D_MODEL_PATH=models/hiyori
LIVE2D_WINDOW_WIDTH=400
LIVE2D_WINDOW_HEIGHT=600

LOG_LEVEL=INFO
```

## 7. 未来 Web 形态的映射

M1 不写任何 HTTP 代码。要转 Web 时：

- **内部事件 → WebSocket 帧**：`{"type": "llm.token", "turn_id": "...", "data": {...}}`，一对一。因为事件本来就是数据结构，不需要重新设计协议。
- **呈现通道换个实现**：Web 形态把 `RendererControl` 实现成"往 WebSocket 发帧"，`stage/channel.py` 换成浏览器版即可——runtime 一行都不用改。
- **需要新增**：连接鉴权（本地随机 token）、音频文件的服务端点（M1 里音频只在本机文件系统里传路径）、断线重连后的状态同步（一条 `sync` 命令回放当前回合状态）。
- **不用改**：`runtime.py` 以下的全部模块。这正是"核心层不许 import GUI / 网络库"这条约束换来的。

## 8. M1 的简化说明

- 情感判断用关键词规则，不接模型
- 不做工具调用，一个回合只有一轮 LLM 调用
- 会话只存在内存里，不落库，关掉程序就没了
- 音频落在临时目录，程序退出时清理
