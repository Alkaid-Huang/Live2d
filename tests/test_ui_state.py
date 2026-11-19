"""界面侧纯逻辑的测试：显示状态、发送排队、延迟打点。

ui/window.py 在 CI 里跑不了（没有 Qt、没有显示器），所以判断逻辑全在
ui/state.py，那些逻辑在这里被盯住。
"""

from __future__ import annotations

import pytest

from contracts import (
    EmotionDetectedEvent,
    ErrorEvent,
    LlmDoneEvent,
    LlmTokenEvent,
    TtsChunkEvent,
    TtsStateEvent,
    TurnCancelledEvent,
    TurnDoneEvent,
    TurnStartEvent,
)
from ui.state import ConversationView, LatencyTracker, SendQueue


def start(view: ConversationView, turn_id: str = "t1") -> None:
    """开一个回合，省得每个用例都写一遍构造。"""
    view.apply(TurnStartEvent(turn_id=turn_id, user_text="在吗"))


def test_turn_start_adds_both_bubbles_and_marks_busy() -> None:
    view = ConversationView()

    assert view.apply(TurnStartEvent(turn_id="t1", user_text="在吗")) is True

    assert [(entry.role, entry.text) for entry in view.entries] == [
        ("user", "在吗"),
        ("assistant", ""),
    ]
    assert view.busy is True
    assert view.status == "正在回复…"


def test_tokens_accumulate_into_the_same_bubble() -> None:
    view = ConversationView()
    start(view)

    view.apply(LlmTokenEvent(turn_id="t1", text="你"))
    view.apply(LlmTokenEvent(turn_id="t1", text="好"))

    assert len(view.entries) == 2
    assert view.entries[-1].text == "你好"
    assert view.entries[-1].status == "streaming"


def test_token_without_a_running_turn_is_ignored() -> None:
    view = ConversationView()

    assert view.apply(LlmTokenEvent(turn_id="t1", text="你")) is False
    assert view.entries == []


def test_llm_done_closes_the_bubble_but_keeps_busy() -> None:
    """文字写完了，语音还在后面：回合没结束，busy 不该掉。"""
    view = ConversationView()
    start(view)

    view.apply(LlmTokenEvent(turn_id="t1", text="你好"))
    view.apply(LlmDoneEvent(turn_id="t1", finish_reason="stop"))

    assert view.entries[-1].status == "done"
    assert view.busy is True


def test_cancel_mid_stream_marks_the_bubble_as_interrupted() -> None:
    view = ConversationView()
    start(view)
    view.apply(LlmTokenEvent(turn_id="t1", text="半句话"))

    view.apply(TurnCancelledEvent(turn_id="t1", reason="user_new_message"))

    assert view.entries[-1].status == "cancelled"
    assert view.busy is False
    assert view.status == "已打断"


def test_cancel_after_the_reply_is_complete_keeps_the_text_intact() -> None:
    """回复已完整（也已进历史），这时失败或被打断，文字不该被标成截断。"""
    view = ConversationView()
    start(view)
    view.apply(LlmTokenEvent(turn_id="t1", text="完整回复"))
    view.apply(LlmDoneEvent(turn_id="t1", finish_reason="stop"))

    view.apply(TurnCancelledEvent(turn_id="t1", reason="error"))

    assert view.entries[-1].status == "done"
    assert view.busy is False
    assert view.status == "出错"


@pytest.mark.parametrize(
    ("state", "expected"),
    [
        ("synthesizing", "合成语音…"),
        ("playing", "播放中…"),
        ("idle", "空闲"),
        ("failed", "语音失败"),
    ],
)
def test_tts_state_drives_the_status_line(state: str, expected: str) -> None:
    view = ConversationView()
    start(view)

    view.apply(TtsStateEvent(turn_id="t1", state=state))

    assert view.status == expected


def test_tts_failure_is_reported_with_its_detail() -> None:
    view = ConversationView()
    start(view)

    view.apply(TtsStateEvent(turn_id="t1", state="failed", detail="连接被重置"))

    assert view.last_error == "语音合成失败：连接被重置"


def test_chunk_shows_the_segment_progress() -> None:
    view = ConversationView()
    start(view)

    view.apply(
        TtsChunkEvent(turn_id="t1", segment_index=1, segment_total=3, path="a.mp3", format="mp3")
    )

    assert view.status == "语音 2/3"


def test_turn_done_goes_back_to_idle() -> None:
    view = ConversationView()
    start(view)
    view.apply(LlmTokenEvent(turn_id="t1", text="你好"))

    view.apply(TurnDoneEvent(turn_id="t1"))

    assert view.busy is False
    assert view.status == "空闲"
    assert view.entries[-1].status == "done"


def test_emotion_is_kept_for_the_status_line() -> None:
    view = ConversationView()
    start(view)

    assert view.apply(EmotionDetectedEvent(turn_id="t1", label="开心", source="rules")) is True

    assert view.last_emotion == "开心"


def test_error_is_shown_and_maps_to_a_human_readable_status() -> None:
    view = ConversationView()

    view.apply(ErrorEvent(turn_id="", code="live2d_load_failed", message="渲染进程没起来"))

    assert view.status == "无模型展示"
    assert view.last_error == "live2d_load_failed：渲染进程没起来"
    assert view.busy is False


def test_a_new_turn_clears_the_previous_error() -> None:
    view = ConversationView()
    view.apply(ErrorEvent(turn_id="", code="llm_error", message="上一轮的错"))

    start(view, turn_id="t2")

    assert view.last_error is None


def test_send_queue_starts_immediately_when_idle() -> None:
    queue = SendQueue()

    decision = queue.submit("  你好  ", active_turn_id=None)

    assert decision.start_now == "你好"
    assert decision.cancel_turn_id is None
    assert queue.pending is None


def test_send_queue_cancels_and_remembers_when_busy() -> None:
    queue = SendQueue()

    decision = queue.submit("第二条", active_turn_id="t1")

    assert decision.start_now is None
    assert decision.cancel_turn_id == "t1"
    assert queue.pending == "第二条"


def test_send_queue_keeps_only_the_latest_pending_message() -> None:
    queue = SendQueue()
    queue.submit("第二条", active_turn_id="t1")
    queue.submit("第三条", active_turn_id="t1")

    assert queue.take_after_turn() == "第三条"
    assert queue.take_after_turn() is None


def test_send_queue_drops_blank_input() -> None:
    queue = SendQueue()

    decision = queue.submit("   ", active_turn_id=None)

    assert decision.start_now is None
    assert queue.pending is None


class FakeClock:
    """手动推进的时钟，免得测试里 sleep。"""

    def __init__(self) -> None:
        self.now = 0.0

    def __call__(self) -> float:
        return self.now


def test_latency_tracker_reports_first_token_first_audio_and_total() -> None:
    clock = FakeClock()
    tracker = LatencyTracker(clock=clock)

    tracker.observe(TurnStartEvent(turn_id="t1", user_text="在吗"))
    clock.now = 1.25
    tracker.observe(LlmTokenEvent(turn_id="t1", text="你"))
    clock.now = 1.40
    tracker.observe(LlmTokenEvent(turn_id="t1", text="好"))
    clock.now = 2.75
    tracker.observe(
        TtsChunkEvent(turn_id="t1", segment_index=0, segment_total=1, path="a.mp3", format="mp3")
    )
    clock.now = 3.00

    summary = tracker.observe(TurnDoneEvent(turn_id="t1"))

    assert summary is not None
    assert summary.first_token_ms == 1250
    assert summary.first_audio_ms == 2750
    assert summary.total_ms == 3000


def test_latency_tracker_skips_points_that_never_happened() -> None:
    clock = FakeClock()
    tracker = LatencyTracker(clock=clock)
    tracker.observe(TurnStartEvent(turn_id="t1", user_text="在吗"))
    clock.now = 0.5

    summary = tracker.observe(TurnCancelledEvent(turn_id="t1", reason="user_stop"))

    assert summary is not None
    assert summary.first_token_ms is None
    assert summary.first_audio_ms is None


def test_latency_tracker_ignores_events_without_a_started_turn() -> None:
    tracker = LatencyTracker(clock=FakeClock())

    assert tracker.observe(TurnDoneEvent(turn_id="ghost")) is None


def test_latency_tracker_forgets_finished_turns() -> None:
    clock = FakeClock()
    tracker = LatencyTracker(clock=clock)
    tracker.observe(TurnStartEvent(turn_id="t1", user_text="在吗"))
    tracker.observe(TurnDoneEvent(turn_id="t1"))
    clock.now = 10.0

    assert tracker.observe(TurnDoneEvent(turn_id="t1")) is None
