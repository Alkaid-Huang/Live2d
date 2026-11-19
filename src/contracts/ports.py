"""端口：实现层必须满足的契约。

这里只有 ``Protocol``，没有任何实现。实现方分别位于：

| 端口 | 实现 |
|---|---|
| ``RendererControl`` | ``stage.channel.RendererChannel`` |
| ``TtsBackend`` | ``tts.edge_impl.EdgeTtsBackend`` |
| ``LlmClient`` | ``llm.router.RouterLlmClient`` |
| ``QueueLike`` | ``multiprocessing.Queue`` |

依赖方向只有一个：实现层 import 本模块，本模块只 import 标准库与 contracts 内部的类型。
"""

from __future__ import annotations

from collections.abc import Iterator, Sequence
from typing import Protocol

from contracts.audio import TtsChunk, VoiceProfile
from contracts.messages import Message


class RendererControl(Protocol):
    """运行时（runtime）向"看得见的地方"派发声音和表情的端口。

    Note:
        三个方法都**不等待播放完成**，调用后立即返回。

    Example:
        ```python
        renderer.play(turn_id="9f3c", segment_index=0, segment_total=1,
                      path="tmp_audio/9f3c-0.mp3", format="mp3")
        renderer.set_emotion(turn_id="9f3c", label="开心")
        renderer.stop("9f3c")
        ```
    """

    def play(
        self,
        *,
        turn_id: str,
        segment_index: int,
        segment_total: int,
        path: str,
        format: str,
    ) -> None:
        """把一片音频排进播放队列。

        不检查文件是否存在——渲染进程自己容错。

        Args:
            turn_id: 所属回合的 id。
            segment_index: 本片序号，从 0 开始。
            segment_total: 本回合总片数，大于 0。
            path: 音频文件路径，字符串形式。
            format: 音频格式，目前恒为 ``"mp3"``。

        Note:
            不抛异常。队列写失败由实现方自己记日志。

        Example:
            ```python
            renderer.play(turn_id="9f3c", segment_index=0, segment_total=2,
                          path="tmp_audio/9f3c-0.mp3", format="mp3")
            ```
        """
        ...

    def set_emotion(self, *, turn_id: str, label: str) -> None:
        """按情感标签换表情、播动作。

        Args:
            turn_id: 所属回合的 id。
            label: 情感标签（中文），取值见 ``emotion.EmotionLabel``。

        Note:
            不抛异常。认不出的标签由渲染进程回落到中性并记日志。

        Example:
            ```python
            renderer.set_emotion(turn_id="9f3c", label="开心")
            ```
        """
        ...

    def stop(self, turn_id: str) -> None:
        """停止播放、口型归位，并丢弃该回合尚未播放的分片。

        Args:
            turn_id: 要停止的回合。空串表示**全局停止**，用于"编排已经结束、
                但播放尚未结束"的场景。

        Note:
            不抛异常。

        Example:
            ```python
            renderer.stop("")      # 不管哪个回合，全停
            renderer.stop("9f3c")  # 只停这一个回合
            ```
        """
        ...


class TtsBackend(Protocol):
    """语音合成后端。

    实现：``tts.edge_impl.EdgeTtsBackend``，由 ``tts.create_tts_backend()`` 装配。
    上层只依赖本协议，不知道具体后端的类型或异常。

    Example:
        ```python
        backend = create_tts_backend("edge", audio_dir=Path("tmp_audio"))
        for chunk in backend.synthesize("你好。", voice, turn_id="9f3c",
                                        segment_index=0, segment_total=1):
            print(chunk.path)
        ```
    """

    def synthesize(
        self,
        text: str,
        voice: VoiceProfile,
        *,
        turn_id: str,
        segment_index: int,
        segment_total: int,
    ) -> Iterator[TtsChunk]:
        """合成**一句话**，产出落盘后的音频分片（``TtsChunk``）。

        是生成器，但内部是阻塞的：edge 后端用 ``asyncio.run`` 等网络返回。

        Args:
            text: 已经切好的一句话。后端只合成这一句，不自己切句。
            voice: 音色档案。
            turn_id: 所属回合，用于匹配 ``cancel()``。
            segment_index: 句子序号，由调用方给出并原样回填到 ``TtsChunk``。
            segment_total: 本回合句子总数，原样回填。

        Raises:
            TtsError: 合成失败或超时。

        Note:
            取消语义：调用 ``cancel(turn_id)`` 之后，本方法在下一次产出前停止迭代，
            不抛异常，并清理尚未交付的半成品文件；已经交付的分片不删。

        Example:
            ```python
            for chunk in backend.synthesize("你好。", voice, turn_id="9f3c",
                                            segment_index=0, segment_total=1):
                print(chunk.path)   # tmp_audio/9f3c-0.mp3
            ```
        """
        ...

    def cancel(self, turn_id: str) -> None:
        """请求取消某个回合的合成。

        幂等，只设置取消标志，不阻塞。

        Args:
            turn_id: 要取消的回合的 id。

        Note:
            不抛异常。

        Example:
            ```python
            backend.cancel("9f3c")
            ```
        """
        ...


class LlmClient(Protocol):
    """流式对话后端。

    实现：``llm.router.RouterLlmClient``（内部走 LiteLLM）。
    上层只依赖本协议，测试里换成一个假的即可，不需要联网。

    Example:
        ```python
        client = RouterLlmClient()
        for delta in client.stream([Message(role="user", content="在吗")],
                                   model="deepseek-chat", provider="deepseek",
                                   api_key=None, base_url=None,
                                   temperature=1.0, timeout=30.0):
            print(delta, end="")
        ```
    """

    def stream(
        self,
        messages: Sequence[Message],
        *,
        model: str,
        provider: str,
        api_key: str | None,
        base_url: str | None,
        temperature: float,
        timeout: float,
    ) -> Iterator[str]:
        """按顺序产出回复的文本增量。

        Args:
            messages: 完整上下文（含 system），调用方负责拼接与裁剪。
            model: 模型名，可以带也可以不带 provider 前缀。
            provider: ``"deepseek"`` 或 ``"openai_compatible"``。
            api_key: API Key；``None`` 表示交给底层库从环境变量读。
            base_url: 自建端点的地址；``None`` 表示用官方地址。
            temperature: 采样温度。
            timeout: 单次请求超时（秒）。

        Raises:
            LLMTimeoutError: 请求超时。
            LLMProviderError: Provider 报错或连不上。

        Note:
            惰性迭代：调用本方法本身不发请求，第一次迭代才开始。

        Example:
            ```python
            deltas = list(client.stream(history, model="deepseek-chat",
                                        provider="deepseek", api_key="sk-...",
                                        base_url=None, temperature=1.0, timeout=30.0))
            reply = "".join(deltas)
            ```
        """
        ...


class QueueLike(Protocol):
    """``multiprocessing.Queue`` 里我们用到的三个方法。

    抽成协议是为了让通道层能用普通对象测试，不需要真的开进程。

    Example:
        ```python
        class FakeQueue:
            def __init__(self) -> None:
                self.items: list[object] = []
            def put(self, item: object) -> None:
                self.items.append(item)
            def put_nowait(self, item: object) -> None:
                self.items.append(item)
            def get_nowait(self) -> object:
                return self.items.pop(0)
        ```
    """

    def put(self, item: object) -> None:
        """阻塞写入一条消息。

        Args:
            item: 要写入的对象，跨进程时必须是可序列化的普通字典。
        """
        ...

    def put_nowait(self, item: object) -> None:
        """立即写入一条消息。

        Args:
            item: 要写入的对象。

        Raises:
            queue.Full: 队列满时（实现方自己决定容量）。
        """
        ...

    def get_nowait(self) -> object:
        """立即取出一条消息。

        Returns:
            队列里的对象。

        Raises:
            queue.Empty: 队列为空时。
        """
        ...
