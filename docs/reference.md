# 接口参考

本页内容全部从 `src/` 的 docstring 与类型注解生成，**不要手改**。改接口就改代码，页面自动跟着变。

想理解"为什么这样设计"，看 [`decisions.md`](decisions.md)；想知道"一次对话怎么走"，看 [`architecture.md`](architecture.md)。

## 0. 符号总表

| 符号 | 层 | 定义在 | 实现/使用方 |
|---|---|---|---|
| `RendererControl` | 端口 | `contracts/ports.py` | `stage.channel.RendererChannel` 实现；`ChatRuntime` 调用 |
| `TtsBackend` | 端口 | `contracts/ports.py` | `tts.edge_impl.EdgeTtsBackend` 实现；`ChatRuntime` 调用 |
| `LlmClient` | 端口 | `contracts/ports.py` | `llm.router.RouterLlmClient` 实现；`ChatRuntime` 调用 |
| `QueueLike` | 端口 | `contracts/ports.py` | `multiprocessing.Queue` 实现；通道与渲染进程使用 |
| `Event` 及 9 个子类 | 契约 | `contracts/events.py` | runtime 发；界面与装配层收 |
| `Message` | 契约 | `contracts/messages.py` | runtime 拼上下文；LLM 层消费 |
| `TtsChunk` / `VoiceProfile` | 契约 | `contracts/audio.py` | TTS 产出；runtime 使用 |
| `LLMError` / `TtsError` | 契约 | `contracts/errors.py` | 各实现层抛出；runtime 翻译成事件 |
| 命令与回传 | 契约 | `stage/protocol.py` | 主进程 ↔ 渲染子进程 |

**什么进这张表**：被两个及以上模块 import，或者跨进程传。只有一个调用方的符号算内部实现，
比如 `ui/state.py` 的 `ConversationView`（只有窗口用）、`stage/lipsync.py` 的 `MouthDriver`
（只有渲染进程用）。它们可以随便改，不需要改文档，但必须保留测试。

---

## 1. 端口

端口只有定义，没有实现。实现层 import 它们，它们不 import 实现层。

### 1.1 RendererControl

::: contracts.ports.RendererControl

### 1.2 TtsBackend

::: contracts.ports.TtsBackend

### 1.3 LlmClient

::: contracts.ports.LlmClient

### 1.4 QueueLike

::: contracts.ports.QueueLike

---

## 2. 事件

所有事件都是 frozen dataclass，都带 `turn_id`，`type` 是类属性而不是字段。
帧形状见 `Event.to_frame()`。

### 2.1 基类与接收方

::: contracts.events.Event

::: contracts.events.EventSink

### 2.2 回合开始与 LLM

::: contracts.events.TurnStartEvent

::: contracts.events.LlmTokenEvent

::: contracts.events.LlmDoneEvent

### 2.3 情感与语音

::: contracts.events.EmotionDetectedEvent

::: contracts.events.TtsStateEvent

::: contracts.events.TtsChunkEvent

### 2.4 结束与错误

::: contracts.events.TurnCancelledEvent

::: contracts.events.TurnDoneEvent

::: contracts.events.ErrorEvent

### 2.5 枚举值域

::: contracts.events.TtsState

::: contracts.events.CancelReason

---

## 3. 数据类型

### 3.1 对话消息

::: contracts.messages.Message

::: contracts.messages.Role

### 3.2 音频

::: contracts.audio.TtsChunk

::: contracts.audio.VoiceProfile

---

## 4. 异常

每一层只向上暴露自己的基类，上层不接触底层库的异常类型。

::: contracts.errors.LLMError

::: contracts.errors.LLMTimeoutError

::: contracts.errors.LLMProviderError

::: contracts.errors.TtsError

---

## 5. 渲染进程协议

主进程与渲染子进程之间只传普通字典。所有 `to_payload()` 产生的就是跨进程传输的内容，
也是将来 WebSocket 帧的 `data`。

### 5.1 命令（主进程 → 渲染进程）

::: stage.protocol.PlayAudioCommand

::: stage.protocol.StopAudioCommand

::: stage.protocol.SetEmotionCommand

::: stage.protocol.QuitCommand

::: stage.protocol.Command

### 5.2 回传（渲染进程 → 主进程）

::: stage.protocol.RendererReadyMessage

::: stage.protocol.RendererFailedMessage

::: stage.protocol.AudioStartedMessage

::: stage.protocol.AudioIdleMessage

::: stage.protocol.RendererMessage

### 5.3 序列化函数

::: stage.protocol.command_from_payload

::: stage.protocol.message_from_payload

::: stage.protocol.message_to_payload

::: stage.protocol.message_to_events

---

## 6. 编排

### 6.1 ChatRuntime

::: runtime.ChatRuntime

### 6.2 模块级常量

::: runtime.DEFAULT_SYSTEM_PROMPT

::: runtime.EMOTION_SOURCE

---

## 7. 实现与工厂

这一节是实现层的公开入口。它们是"怎么造出一个端口实现"，不是端口本身。

### 7.1 LLM

::: llm.router.RouterLlmClient

::: llm.router.stream_reply

::: llm.router.normalize_model_name

### 7.2 语音

::: tts.create_tts_backend

::: tts.base.edge_profile

::: tts.base.split_sentences

### 7.3 情感

::: emotion.rules.detect

::: emotion.mapping.resolve

::: emotion.mapping.EmotionLabel

::: emotion.mapping.EmotionCue

### 7.4 模型文件

::: stage.model_files.resolve_model_json

::: stage.model_files.ModelNotFound
