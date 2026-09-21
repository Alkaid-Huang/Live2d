"""tts.base 的测试：纯函数、数据类和装配入口。"""

from __future__ import annotations

import pytest

from tts import create_tts_backend
from tts.base import edge_profile, split_sentences
from tts.edge_impl import EdgeTtsBackend


def test_split_chinese_punctuation() -> None:
    assert split_sentences("你好。今天怎么样？") == ["你好。", "今天怎么样？"]


def test_split_english_periods() -> None:
    assert split_sentences("Hello. How are you?") == ["Hello.", "How are you?"]


def test_newline_is_a_boundary() -> None:
    assert split_sentences("第一行\n第二行") == ["第一行", "第二行"]


def test_consecutive_punctuation_merged() -> None:
    assert split_sentences("哈哈！！！") == ["哈哈！！！"]


def test_decimal_period_is_not_split() -> None:
    assert split_sentences("圆周率约等于 3.14。") == ["圆周率约等于 3.14。"]


def test_version_number_is_not_split() -> None:
    assert split_sentences("版本 2.0 上线了") == ["版本 2.0 上线了"]


def test_no_ending_punctuation_returns_whole_text() -> None:
    assert split_sentences("没有标点的一句话") == ["没有标点的一句话"]


def test_empty_and_blank_return_nothing() -> None:
    assert split_sentences("") == []
    assert split_sentences("   ") == []


def test_blank_sentences_are_dropped() -> None:
    assert split_sentences("你好。\n\n\n") == ["你好。"]


def test_edge_profile() -> None:
    profile = edge_profile("zh-CN-XiaoxiaoNeural")
    assert profile.backend == "edge"
    assert profile.params == {"voice": "zh-CN-XiaoxiaoNeural", "rate": "+0%"}


def test_edge_profile_rate_override() -> None:
    profile = edge_profile("zh-CN-XiaoxiaoNeural", rate="+10%")
    assert profile.params["rate"] == "+10%"


def test_create_edge_backend(tmp_path: object) -> None:
    backend = create_tts_backend("edge", audio_dir=tmp_path)
    assert isinstance(backend, EdgeTtsBackend)


def test_create_unknown_backend_raises(tmp_path: object) -> None:
    with pytest.raises(ValueError):
        create_tts_backend("local", audio_dir=tmp_path)
