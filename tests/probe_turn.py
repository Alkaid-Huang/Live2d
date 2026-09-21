"""手动端到端探针：不启动界面，真实跑一轮 LLM → 情感 → 语音。

**CI 不跑这个文件**（名字不是 test_*，pytest 不会收集），因为它要联网、要花 API
额度。用它是为了把"链路通不通"和"界面接对没有"分开：

- 通了 → 剩下的问题只可能在界面或渲染
- 没通 → 报错直接指向 LLM 或 TTS

它和 tests/probe_renderer.py 是一对：那个验渲染这一半，这个验文字与语音那一半。

用法（在项目根目录）：

    .venv\\Scripts\\python.exe tests\\probe_turn.py
    .venv\\Scripts\\python.exe tests\\probe_turn.py "用一句话介绍你自己"
    .venv\\Scripts\\python.exe tests\\probe_turn.py "用一句话介绍你自己" --turns 3

``--turns N`` 连跑 N 轮。第一轮包含 ``import litellm`` 的一次性开销（实测 3 秒出头），
从第二轮开始才是稳态延迟——要判断"首字 3 秒"这个指标，看的是稳态那一轮，
因为真实使用中程序启动后第一句话只有一次。

退出码：0 = 本轮跑完且拿到了音频分片；1 = 跑完了但没有音频；2 = 出现错误事件。
生成的音频留在 TTS_AUDIO_DIR 里（默认 tmp_audio/），可以直接点开听。
"""

from __future__ import annotations

import sys
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(REPO_ROOT / "src"))

from config import Settings  # noqa: E402
from events import (  # noqa: E402
    EmotionDetectedEvent,
    ErrorEvent,
    Event,
    LlmTokenEvent,
    TtsChunkEvent,
    TtsStateEvent,
)
from runtime import ChatRuntime  # noqa: E402
from tts import create_tts_backend, edge_profile  # noqa: E402
from ui.state import LatencyTracker, TurnLatency  # noqa: E402

DEFAULT_QUESTION = "用一句话介绍你自己"


def main(argv: list[str]) -> int:
    """跑 N 轮并打印结果。"""
    settings = Settings()
    question, turns = _parse_args(argv[1:])
    if turns < 1:
        print("--turns 至少是 1")
        return 2

    audio_dir = REPO_ROOT / settings.tts_audio_dir
    audio_dir.mkdir(parents=True, exist_ok=True)

    events: list[Event] = []
    summaries: list[TurnLatency] = []
    errors: list[ErrorEvent] = []
    # 用单元素列表而不是普通变量：闭包里要能换掉它（每轮一个新的打点器）。
    tracker = [LatencyTracker()]

    def sink(event: Event) -> None:
        summary = tracker[0].observe(event)
        if summary is not None:
            summaries.append(summary)
        events.append(event)
        if isinstance(event, ErrorEvent):
            errors.append(event)
        _echo(event)

    runtime = ChatRuntime(
        sink=sink,
        # 不传 renderer：没有渲染进程，音频只落盘不播放（runtime 允许 renderer 为 None）。
        tts_backend=create_tts_backend(settings.tts_backend, audio_dir=audio_dir),
        settings=settings,
        voice=edge_profile(settings.tts_edge_voice, settings.tts_edge_rate),
    )

    print(f"提问：{question}")
    print(f"模型：{settings.llm_provider}/{settings.llm_model} · 语音：{settings.tts_edge_voice}")
    chunks: list[TtsChunkEvent] = []
    for index in range(turns):
        marker = len(events)
        tracker[0] = LatencyTracker()
        print("-" * 60)
        print(f"第 {index + 1}/{turns} 轮")
        runtime.send(question)
        print()
        turn_chunks = [
            event for event in events[marker:] if isinstance(event, TtsChunkEvent)
        ]
        chunks.extend(turn_chunks)
        _report(summaries[-1:], turn_chunks)

    if errors:
        return 2
    return 0 if chunks else 1


def _parse_args(args: list[str]) -> tuple[str, int]:
    """从命令行参数里取出问题和轮数。"""
    turns = 1
    rest = list(args)
    if "--turns" in rest:
        position = rest.index("--turns")
        try:
            turns = int(rest[position + 1])
        except (IndexError, ValueError):
            print("--turns 后面要跟正整数，例如 --turns 3")
            raise SystemExit(2) from None
        del rest[position : position + 2]
    return (rest[0] if rest else DEFAULT_QUESTION), turns


def _echo(event: Event) -> None:
    """把事件按人看得懂的样子打出来。"""
    if isinstance(event, LlmTokenEvent):
        print(event.text, end="", flush=True)
    elif isinstance(event, EmotionDetectedEvent):
        print(f"\n[情感] {event.label}（来源 {event.source}）")
    elif isinstance(event, TtsStateEvent):
        print(f"[语音] {event.state}")
    elif isinstance(event, TtsChunkEvent):
        print(f"[分片] 第 {event.segment_index + 1}/{event.segment_total} 段 {event.path}")
    elif isinstance(event, ErrorEvent):
        print(f"[错误] {event.code}：{event.message}")


def _report(summaries: list[TurnLatency], chunks: list[TtsChunkEvent]) -> None:
    """打印延迟与音频落盘情况。"""
    if summaries:
        summary = summaries[0]
        print(
            f"延迟：首字 {_ms(summary.first_token_ms)} / "
            f"首音 {_ms(summary.first_audio_ms)} / 整轮 {summary.total_ms}ms"
        )
    print(f"音频分片：{len(chunks)} 段")
    for chunk in chunks:
        path = Path(chunk.path)
        size = path.stat().st_size if path.exists() else 0
        print(f"  {path.name}  {size / 1024:.1f} KB  {chunk.format}")


def _ms(value: int | None) -> str:
    """延迟数字 → 文字。没打到的点写 n/a。"""
    return "n/a" if value is None else f"{value}ms"


if __name__ == "__main__":
    raise SystemExit(main(sys.argv))
