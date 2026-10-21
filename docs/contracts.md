# 接口与事件契约

M1 没有 HTTP 接口。这份文件冻结的是**模块之间怎么说话**：事件格式、事件顺序、取消语义、各模块的边界。

**改这里等于改两端，必须先改文档再改代码。**

本文中的 Python 签名描述的是调用方可以依赖的 M1 接口。只供单个模块内部使用、或明确标为测试替换点的符号不算公开契约。实现可以增加私有 helper，但不能单方面改变这里的数据形状、阻塞语义或异常边界。

## 1. 进程与模块边界

**主进程（桌面壳）**

| 模块 | 职责 |
|---|---|
| `ui/` | 窗口、输入框、对话显示、状态提示 |
| `runtime.py` | 会话编排：什么时候调 LLM、什么时候调 TTS、什么时候取消 |
| `llm/` | LLM 调用（LiteLLM 封装，流式） |
| `emotion/` | 情感判断与映射（输出抽象名字，不碰渲染库） |
| `tts/` | 语音合成（M1 跑在主进程的后台线程里） |
| `stage/` | 主进程侧的呈现通道：把 runtime 的播放/表情命令送进渲染子进程，并把回传翻译成事件 |

**渲染子进程**：`stage/renderer.py`，加载模型、播放音频、渲染画面。

**舞台层**（`src/stage/`）是主进程侧的那一半：`channel.py` 负责收发，`protocol.py` 定义消息，`playback.py` 管待播队列，`lipsync.py` 算口型，`cues.py` 挑动作，`model_files.py` 找模型。它叫 `stage` 而不是 `live2d`，因为第三方库 live2d-py 的顶层模块就叫 `live2d`，同名会在 `import live2d.v3` 时导到自己身上。

三个决定要说清楚：

- **音频播放放在渲染进程**，不放主进程。因为口型要用正在播放的那段音频的音量，同一个进程里最省事。
- **TTS 在 M1 跑在主进程的后台线程里**（edge-tts 是网络流，没有本地模型加载，不需要单独开进程）。将来换成本地模型时把它整体挪进子进程，**上层不用改**——这就是接口抽象的目的。
- **两个进程之间是双向的**：主进程发命令（播音频、换表情、停播放、退出），渲染进程回传状态（就绪、失败、开始播、播完）。回传存在的理由有两个：`tts.state` 的 `playing` / `idle` 只有渲染进程知道，而 `live2d_load_failed` 也只能由它上报。

runtime 不认识队列，也不认识 pygame：它只依赖 `runtime.RendererControl` 的三个方法（`play` / `set_emotion` / `stop`），实现是 `stage/channel.py`。要不要接渲染进程是装配时决定的——不传就不会有声音，文本照常（单元测试就是这么跑的）。

**线程与所有权**：

- `ChatRuntime.send()` 是阻塞调用。界面装配层负责把它放进后台线程；runtime 不创建、不 join 线程。
- `EventSink` 可能从回合线程或界面线程被调用。sink 的实现必须自己保证跨线程投递安全；桌面壳通过 Qt 信号的排队连接交给界面线程。
- `TtsBackend` 由装配层注入。runtime 只持有协议，不知道 `edge_tts` 的存在。
- 渲染播放由渲染进程拥有。runtime 发出命令后不等待音频播完，`turn.done` 也不代表播放结束。

## 2. 统一事件

跨进程、跨界面只传一种东西：`Event`，定义在 `src/events.py`。都是 dataclass，都带 `type` 和 `turn_id`。

| Python 类 | type | 字段（除 `turn_id` 外） | 发送方 → 接收方 | 含义 |
|---|---|---|---|---|
| `TurnStartEvent` | `turn.start` | `user_text: str` | runtime → 界面 | 新回合开始 |
| `LlmTokenEvent` | `llm.token` | `text: str` | runtime → 界面 | 一段增量文本 |
| `LlmDoneEvent` | `llm.done` | `finish_reason: str` | runtime → 界面 | 回复生成完毕 |
| `EmotionDetectedEvent` | `emotion.detected` | `label: str`, `source: str` | runtime → 界面 | 本回合的情感 |
| `TtsStateEvent` | `tts.state` | `state: TtsState`, `detail: str = ""` | runtime / 舞台适配器 → 界面 | 合成或播放状态变化 |
| `TtsChunkEvent` | `tts.chunk` | `segment_index: int`, `segment_total: int`, `path: str`, `format: str` | runtime → 界面 | 一段音频就绪 |
| `TurnCancelledEvent` | `turn.cancelled` | `reason: CancelReason` | runtime → 界面 | 正在编排的回合被取消或失败 |
| `TurnDoneEvent` | `turn.done` | — | runtime → 界面 / 装配层 | 编排结束；播放可能继续 |
| `ErrorEvent` | `error` | `code: str`, `message: str` | 任意模块经 sink → 界面 | 出错 |

字段值域：`TtsState` 为 `idle` / `synthesizing` / `playing` / `failed`；`CancelReason` 为 `user_new_message` / `user_stop` / `error`；`emotion.detected.source` 在 M1 为 `rules`；`llm.done.finish_reason` 在 M1 为 `stop`；`tts.chunk.segment_index` 从 0 开始，`segment_total` 大于 0。

渲染进程不直接接收 `Event`：装配层把 `emotion.detected` 和 `tts.chunk` 分别翻译成 `RendererControl.set_emotion()` / `play()`，把取消翻译成 `stop()`。

所有事件都是 frozen dataclass，公共字段都是不可变值。`Event.to_frame()` 产生跨 Web 接缝的字典：

```python
{"type": "llm.token", "turn_id": "...", "data": {"text": "你"}}
```

`turn_id` 只放在帧顶层，不重复放进 `data`。`path` 是字符串而不是 `Path`，因为事件必须能直接序列化。

**界面从第一天就要显示 `synthesizing`**，不能假设语音是瞬间出来的。将来换成本地模型，第一次出声可能要等几十秒，加载提示是必需品不是装饰。

其中 `synthesizing` / `failed` 由 runtime 发（它知道合成这件事），`playing` / `idle` 由渲染进程回传后经 `stage.protocol.message_to_events()` 翻译而来（只有它知道音频在不在响）。**`turn_id` 为空串表示这条事件不属于任何回合**——目前只有启动期的错误会这样（比如模型加载失败），此时回合还没开始。

`playing` / `idle` 可能在 `turn.done` 之后到达，但仍沿用原回合的 `turn_id`。接收方不能因为看到过 `turn.done` 就丢弃播放状态。

## 3. 事件顺序

一次正常回合：

```
turn.start
llm.token × N          逐字推给界面
llm.done
emotion.detected       回复生成完才能判断情感（M1 用关键词规则）
tts.state(synthesizing)
tts.chunk(0/N)、tts.chunk(1/N) …        逐片交给渲染进程
turn.done              编排结束；音频可能仍在排队或播放
   ↓ 以下是原 turn_id 的播放阶段，不代表又开始了新回合
tts.state(playing) → … → tts.state(idle)   播完最后一片才回到 idle
```

没有可合成文本时，事件序列可以省略 `tts.state(synthesizing)`、`tts.chunk` 和播放阶段，但 `turn.start`、`llm.done`、`emotion.detected`、`turn.done` 仍按上述顺序出现。

**`turn.done` 不等播放结束**，这是有意的：`send()` 由界面层放在工作线程里跑，如果它要等语音播完才返回，那个线程会被占用好几秒，而这段时间界面什么都不能做。参照项目也是这个处理方式——主进程派发完就继续，播放归渲染子进程管。

因此本文把“回合”定义为**编排回合**：从 `turn.start` 到 `turn.done`。`turn.done` 之后仍在进行的播放叫**播放阶段**，它沿用原 `turn_id`，但不是新的编排回合。`ChatRuntime.active_turn_id` 只表示编排是否还在跑，变成 `None` 不代表播放已经停止。

代价是"打断"分成两半，装配时必须都接上：runtime 负责停合成（`tts.cancel`）与停播放（`RendererControl.stop`），界面层负责把新输入送进 runtime。M1-6 装配时如果只接了前一半，表现就是"新消息来了，文本停了但旧语音还在响"。

播放阶段打断的规则：

- 用户发送新消息或手动停止时，上一回合只要还可能正在播放，就必须停止旧音频并丢弃它的待播分片。
- 已经发出过 `turn.done` 的回合不再补发 `turn.cancelled`；`turn.cancelled` 只用于终止仍在编排中的回合。
- `RendererControl.stop("")` 是全局停止，可覆盖“编排已经结束、但播放尚未结束”的场景。
- 界面不能用 `active_turn_id is None` 推断“没有声音”。M1 当前装配只保存编排中的 `turn_id`，因此**已知尚未闭环**：`turn.done` 后按停止或发送新消息时，旧语音可能继续播放。后续修复必须补上最后派发 `turn_id` 的保存与停止调用，不能把这一现象解释为契约允许。

被取消的回合：

```
turn.cancelled(reason)
  ↓  之后不再产生该 turn_id 的任何事件
  渲染进程立刻停止播放、口型归位（含丢掉队列里同回合的后续分片）
```

`reason` 取值：`user_new_message`（用户又发了一条）/ `user_stop`（手动停止）/ `error`。

**取消是硬约束**：在编排中发出 `turn.cancelled` 之后，属于这个 `turn_id` 的后续编排事件一律丢弃，不许漏出半句。播放阶段被打断不发 `turn.cancelled`，但必须停止该回合的音频和待播分片。

## 4. 模块接口（M1 冻结的部分）

### 公共类型

```python
EventSink = Callable[[Event], None]

@dataclass(frozen=True, slots=True)
class Message:
    role: Literal["system", "user", "assistant"]
    content: str
```

`Message.to_payload()` 只输出 `{"role": ..., "content": ...}`，是送给 LiteLLM 的稳定形状。

### 4.1 Runtime

```python
class ChatRuntime:
    def __init__(
        self,
        *,
        sink: EventSink,
        tts_backend: TtsBackend,
        settings: Settings,
        voice: VoiceProfile,
        system_prompt: str = DEFAULT_SYSTEM_PROMPT,
        session_id: str | None = None,
        renderer: RendererControl | None = None,
    ) -> None: ...

    @property
    def history(self) -> tuple[Message, ...]: ...

    @property
    def active_turn_id(self) -> str | None: ...

    def send(self, user_text: str) -> str: ...

    def cancel(
        self,
        turn_id: str,
        reason: CancelReason = "user_stop",
    ) -> bool: ...
```

- 一个 `ChatRuntime` 管一个会话，内存里保存 system、user、assistant 消息。`system_prompt` 只用于初始化会话，router 不负责拼上下文。
- `send()` **阻塞到编排结束**，返回本回合的 `turn_id`。成功、业务错误和取消都通过 sink 发事件；调用方负责把 `send()` 放进后台线程。
- `send()` 只接受非空文本。空消息抛 `ValueError`；上一回合仍在编排时再调用抛 `RuntimeError`，不隐式取消或并行执行。
- `cancel()` **不阻塞**。只有 `turn_id` 与当前编排回合一致时，才设置取消标志、调用 `TtsBackend.cancel()` 和 `RendererControl.stop()`，并返回 `True`；否则返回 `False`。
- `active_turn_id` 只表示仍在编排的回合。发出 `turn.done` 或 `turn.cancelled` 后它就是 `None`，即便渲染进程还在播放该回合的音频。
- `history` 返回当前消息的只读快照。中途取消的助手回复不进入历史；已经发出的用户消息保留。
- `renderer=None` 是合法用法：文本、情感事件和 TTS 仍运行，只是不派发播放与表情命令。

`RendererControl` 是 runtime 唯一认识的呈现接缝：

```python
class RendererControl(Protocol):
    def play(
        self,
        *,
        turn_id: str,
        segment_index: int,
        segment_total: int,
        path: str,
        format: str,
    ) -> None: ...

    def set_emotion(self, *, turn_id: str, label: str) -> None: ...

    def stop(self, turn_id: str) -> None: ...
```

三个方法都不等待播放完成。`stop("")` 表示停止当前所有播放和待播分片；非空 `turn_id` 只影响该回合。

### 4.2 界面接缝

界面层把用户动作变成事件消费者可接收的信号，不直接调用 LLM、TTS 或渲染库。`ChatWindow` 暴露：

```python
user_submitted = pyqtSignal(str)     # 用户提交的非空原文
stop_requested = pyqtSignal()        # 用户按停止
event_received = pyqtSignal(object)  # 工作线程 → 界面线程的事件投递

def apply_event(self, event: Event) -> None: ...
def view_state(self) -> ConversationView: ...
```

装配层负责连接 `user_submitted`、`stop_requested` 和 `event_received`。工作线程不能直接操作 Qt 控件。

`ConversationView` 是窗口背后的纯逻辑，只依赖 `Event`：

```python
@dataclass
class Entry:
    role: Literal["user", "assistant"]
    text: str = ""
    status: Literal["streaming", "done", "cancelled"] = "done"

@dataclass
class ConversationView:
    entries: list[Entry] = field(default_factory=list)
    status: str = IDLE_STATUS
    busy: bool = False
    last_emotion: str | None = None
    last_error: str | None = None

    def apply(self, event: Event) -> bool: ...
```

`apply()` 返回是否改变了显示状态。`busy` 只表示编排是否进行中，不能当作“是否还在播放”的依据。播放阶段的状态仍由后续 `tts.state(playing|idle)` 更新。

`SendQueue` 只决定输入怎么处理，不创建线程：

```python
@dataclass(frozen=True)
class SendDecision:
    start_now: str | None = None
    cancel_turn_id: str | None = None

class SendQueue:
    @property
    def pending(self) -> str | None: ...

    def submit(
        self,
        text: str,
        *,
        active_turn_id: str | None,
    ) -> SendDecision: ...

    def take_after_turn(self) -> str | None: ...
```

- 空闲时 `submit()` 返回 `start_now`；编排中时返回 `cancel_turn_id` 并记住最新待发文本。
- 连续提交时后来者覆盖前者；空文本被忽略。
- 当前回合发出 `turn.done` 或 `turn.cancelled` 后，由装配层调用 `take_after_turn()` 放行下一条。

延迟观测接口：

```python
@dataclass(frozen=True)
class TurnLatency:
    turn_id: str
    first_token_ms: int | None
    first_audio_ms: int | None
    total_ms: int

class LatencyTracker:
    def __init__(self, *, clock: Callable[[], float] = time.monotonic) -> None: ...
    def observe(self, event: Event) -> TurnLatency | None: ...
```

这是界面/装配层的可选观测接口，口径为：

- 首字：`turn.start` → 第一个 `llm.token`
- 首音：`turn.start` → 第一个 `tts.chunk`
- 整轮：`turn.start` → `turn.done` 或 `turn.cancelled`

### 4.3 LLM

```python
def stream_reply(
    messages: Sequence[Message],
    model: str,
    *,
    provider: str = "deepseek",
    api_key: str | None = None,
    base_url: str | None = None,
    temperature: float = 1.0,
    timeout: float = 30.0,
) -> Iterator[str]: ...
```

- 惰性迭代：调用函数本身不发起请求，第一次迭代才开始请求。
- 产出纯文本增量，不带 Provider 特有字段；空 delta 或只有统计信息的帧不产出。
- 拼 prompt、维护上下文、检查取消是 runtime 的责任，router 不负责。
- `provider` 与模型名前缀由 router 统一处理。已带已知 provider 前缀的模型名原样使用；`openai_compatible` 会给未知前缀补 `openai/`；其他 provider 补自身的 provider 前缀。
- 失败统一翻译为 `LLMTimeoutError`（`llm_timeout`）或 `LLMProviderError`（`llm_error`）。上层不捕获 LiteLLM 异常。
- 测试必须替换 LiteLLM 调用点，不发真实网络请求。

### 4.4 TTS

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

- `text` 是已经切好的一句话，后端只合成这一句。
- `segment_index` / `segment_total` 由 runtime 传入并原样回填到 `TtsChunk`；序号属于切句者，不属于后端。
- `cancel(turn_id)` 幂等，只设置取消标志。`synthesize()` 在下一次产出前检查标志；取消后安静停止，不抛异常，并清理尚未交付的半成品文件。已交付的分片不删，因为渲染进程可能正在播放。
- 后端失败统一抛 `TtsError`（`tts_error`）；上层不接触 `edge_tts` 的类型或异常。
- 测试用假后端，不发真实网络请求。

```python
@dataclass(frozen=True, slots=True)
class TtsChunk:
    path: Path
    format: str
    segment_index: int
    segment_total: int
```

`TtsChunk` **没有 `duration_ms`**：M1 没有消费者，而且不同后端无法以同等代价提供该值（ADR 0001）。

音色档案：

```python
@dataclass(frozen=True, slots=True)
class VoiceProfile:
    backend: str
    params: Mapping[str, str]
```

- edge：`edge_profile(voice, rate="+0%")` 产生 `backend="edge"`，`params={"voice": ..., "rate": ...}`。
- local（预留，M1 不实现）：`model_path`、`ref_audio`、`ref_text`、`language`。
- 后端专属参数留在 `params` 中，不拍平为公共字段。

装配与切句：

```python
def create_tts_backend(backend: str, *, audio_dir: Path) -> TtsBackend: ...
def split_sentences(text: str) -> list[str]: ...
```

`create_tts_backend()` 是唯一选择具体后端的位置；M1 只接受 `"edge"`，未知值抛 `ValueError`。`split_sentences()` 按中英文句末标点和换行切句，返回去空白后的非空句子。

### 4.5 情感

```python
class EmotionLabel(StrEnum):
    HAPPINESS = "开心"
    SADNESS = "难过"
    ANGER = "生气"
    SURPRISE = "惊讶"
    FEAR = "害怕"
    DISGUST = "厌恶"
    NEUTRAL = "中性"

@dataclass(frozen=True, slots=True)
class EmotionCue:
    motion_group: str
    expression: str

def detect(text: str) -> EmotionLabel: ...
def resolve(label: EmotionLabel) -> EmotionCue: ...
```

- `detect()` 是纯函数；空文本或未命中关键词返回 `中性`。
- `EmotionCue` 只输出抽象动作组名和表情名（例如 `happiness`、`smile`），不输出 live2d-py 参数。
- 未映射标签由 `resolve()` 回落到 `中性` 并记录 warning，不许静默失败。

### 4.6 渲染进程与舞台层

runtime 只依赖上面的 `RendererControl`。桌面实现 `RendererChannel`：

```python
class QueueLike(Protocol):
    def put(self, item: object) -> None: ...
    def put_nowait(self, item: object) -> None: ...
    def get_nowait(self) -> object: ...

class RendererChannel:
    def __init__(
        self,
        *,
        command_queue: QueueLike,
        message_queue: QueueLike,
    ) -> None: ...

    def play(
        self,
        *,
        turn_id: str,
        segment_index: int,
        segment_total: int,
        path: str,
        format: str,
    ) -> None: ...
    def set_emotion(self, *, turn_id: str, label: str) -> None: ...
    def stop(self, turn_id: str) -> None: ...
    def quit(self) -> None: ...
    def drain_messages(self) -> tuple[Message, ...]: ...
```

`drain_messages()` 非阻塞取走当前可用的全部回传。坏对象、未知类型或字段类型不匹配只记 warning 并丢弃，不向界面抛异常。

主进程 → 渲染进程的命令：

| Python 类 | `type` | 字段 | 作用 |
|---|---|---|---|
| `PlayAudioCommand` | `play_audio` | `turn_id` / `segment_index` / `segment_total` / `path` / `format` | 播一段音频 |
| `SetEmotionCommand` | `set_emotion` | `turn_id` / `label` | 换表情并按情感播动作 |
| `StopAudioCommand` | `stop_audio` | `turn_id` | 停播、口型归位、丢弃同回合待播分片 |
| `QuitCommand` | `quit` | — | 退出渲染子进程 |
| `switch_model` | `switch_model` | — | 预留，M1 不实现 |

渲染进程 → 主进程的回传：

| Python 类 | `type` | 字段 | 翻译成 |
|---|---|---|---|
| `RendererReadyMessage` | `renderer.ready` | `model_path` | 没有事件，只是启动运维信号 |
| `RendererFailedMessage` | `renderer.failed` | `code` / `message` | `error`，`turn_id=""` |
| `AudioStartedMessage` | `audio.started` | `turn_id` / `segment_index` | `tts.state(playing)` |
| `AudioIdleMessage` | `audio.idle` | `turn_id` | `tts.state(idle)` |

序列化与反序列化入口：

```python
def command_from_payload(payload: Mapping[str, object]) -> Command: ...
def message_from_payload(payload: Mapping[str, object]) -> Message: ...
def message_to_payload(message: Message) -> dict[str, object]: ...
def message_to_events(message: Message) -> tuple[Event, ...]: ...
```

跨进程只传普通字典，不 pickle 自定义对象。`type` 在字典顶层；布尔值不能冒充整数序号。未知 `type` 或必需字段类型错误由反序列化函数抛 `ValueError`，由接收侧记录并丢弃；未知额外字段可忽略，以允许前向兼容。

渲染子进程入口：

```python
def run_renderer_process(
    *,
    model_path: str | Path,
    width: int,
    height: int,
    command_queue: QueueLike,
    message_queue: QueueLike,
) -> int: ...
```

模型加载失败时渲染进程**不退出**，退化为无模型展示，并回一条 `renderer.failed`。音频播放和口型只在渲染进程内处理主进程传来的音频文件。

## 5. 错误码

| code | 含义 |
|---|---|
| `llm_timeout` | LLM 请求超时 |
| `llm_error` | LLM 返回错误 |
| `tts_error` | 语音合成失败 |
| `live2d_load_failed` | Live2D 起不来或模型加载失败——界面退化成无模型展示（窗口还在、文字照常），不许直接崩 |
| `invalid_request` | 参数不合法 |
| `internal_error` | runtime 未归类的内部异常；必须记录 traceback 并终止当前编排 |
| `cancelled` | 保留值，M1 不通过 `error` 发送；取消使用 `turn.cancelled` |

## 6. 配置项

配置只从项目根目录的 `.env` 加载，环境变量优先于文件。变量名大小写不敏感，未知变量忽略。仓库只提交 `.env.example`；程序不提供图形化配置。

| `.env` 键 | `Settings` 字段 | 类型 | 默认值 | 校验/说明 |
|---|---|---|---|---|
| `LLM_PROVIDER` | `llm_provider` | `deepseek` \| `openai_compatible` | `deepseek` | 非法值在加载时拒绝 |
| `LLM_MODEL` | `llm_model` | `str` | `deepseek-chat` | 去空白后不能为空 |
| `LLM_API_KEY` | `llm_api_key` | `str` | `""` | 允许加载时为空；调用 LLM 前必须填写 |
| `LLM_BASE_URL` | `llm_base_url` | `str` | `""` | `openai_compatible` 调用前必须填写 |
| `LLM_TEMPERATURE` | `llm_temperature` | `float` | `1.0` | 范围 `0.0..2.0` |
| `TTS_BACKEND` | `tts_backend` | `edge` | `edge` | M1 不支持其他值 |
| `TTS_EDGE_VOICE` | `tts_edge_voice` | `str` | `zh-CN-XiaoxiaoNeural` | 去空白后不能为空 |
| `TTS_EDGE_RATE` | `tts_edge_rate` | `str` | `+0%` | 原样交给 edge 后端 |
| `TTS_AUDIO_DIR` | `tts_audio_dir` | `str` | `tmp_audio` | 去空白后不能为空；相对路径按项目根解析 |
| `LIVE2D_MODEL_PATH` | `live2d_model_path` | `str` | `models/hiyori` | 非空；相对路径按项目根解析；目录或模型 JSON 都接受 |
| `LIVE2D_WINDOW_WIDTH` | `live2d_window_width` | `int` | `400` | 必须大于 0 |
| `LIVE2D_WINDOW_HEIGHT` | `live2d_window_height` | `int` | `600` | 必须大于 0 |
| `LOG_LEVEL` | `log_level` | `str` | `INFO` | 非法名称回退到 `INFO` |

`Settings.require_llm_credentials()` 在真正调用 LLM 前执行：缺 API Key，或选择了 `openai_compatible` 却缺 Base URL，都抛 `RuntimeError`，由 runtime 翻译成 `invalid_request`。配置加载本身不因缺 Key 而失败。

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

## 9. 接口变更检查

改变本文件中的任一数据形状、事件顺序、阻塞语义或取消行为时，至少检查：

1. 事件生产方、消费方和现有测试是否同时更新。
2. `turn.done` 后仍可能到达的播放状态是否仍被接收。
3. 取消是否同时覆盖合成、正在播放的音频和待播分片。
4. 核心层是否仍没有引入 GUI、网络或具体 TTS 后端类型。
5. `.env.example` 是否记录了新增或改名的配置。
