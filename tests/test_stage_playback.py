"""播放排队的测试，重点是取消时的边界情况。"""

from __future__ import annotations

from stage.playback import PendingChunk, PlaybackPlanner


def chunk(turn_id: str, index: int) -> PendingChunk:
    return PendingChunk(turn_id=turn_id, segment_index=index, path=f"{turn_id}-{index}.mp3")


def test_chunks_are_played_in_order() -> None:
    planner = PlaybackPlanner()
    planner.push(chunk("t1", 0))
    planner.push(chunk("t1", 1))

    assert planner.take_next() == chunk("t1", 0)
    planner.finish_current()
    assert planner.take_next() == chunk("t1", 1)
    planner.finish_current()
    assert planner.take_next() is None


def test_take_next_does_nothing_while_something_is_playing() -> None:
    planner = PlaybackPlanner()
    planner.push(chunk("t1", 0))
    planner.push(chunk("t1", 1))
    planner.take_next()

    assert planner.take_next() is None
    assert planner.has_pending is True


def test_take_next_with_empty_queue() -> None:
    assert PlaybackPlanner().take_next() is None


def test_stop_drops_pending_chunks_of_that_turn_only() -> None:
    planner = PlaybackPlanner()
    planner.push(chunk("t1", 1))
    planner.push(chunk("t2", 0))

    assert planner.stop("t1") is None
    assert planner.take_next() == chunk("t2", 0)


def test_stop_returns_the_current_chunk_when_it_belongs_to_that_turn() -> None:
    planner = PlaybackPlanner()
    planner.push(chunk("t1", 0))
    planner.push(chunk("t1", 1))
    assert planner.take_next() == chunk("t1", 0)

    stopped = planner.stop("t1")

    assert stopped == chunk("t1", 0)
    assert planner.current is None
    assert planner.has_pending is False


def test_stop_leaves_another_turn_playing() -> None:
    """正在播的是别的回合时，这次取消不该把它停掉。"""
    planner = PlaybackPlanner()
    planner.push(chunk("t2", 0))
    planner.take_next()

    assert planner.stop("t1") is None
    assert planner.current == chunk("t2", 0)


def test_empty_turn_id_stops_everything() -> None:
    planner = PlaybackPlanner()
    planner.push(chunk("t1", 0))
    planner.push(chunk("t2", 0))
    planner.take_next()

    stopped = planner.stop("")

    assert stopped == chunk("t1", 0)
    assert planner.current is None
    assert planner.has_pending is False
