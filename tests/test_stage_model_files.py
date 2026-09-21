"""模型路径解析：目录和 json 两种写法都要认，认不出要给能照着改的报错。"""

from __future__ import annotations

from pathlib import Path

import pytest

from stage.model_files import ModelNotFound, is_model_json, resolve_model_json


def write_model(directory: Path, name: str = "Hiyori.model3.json") -> Path:
    path = directory / name
    path.write_text("{}", encoding="utf-8")
    return path


def test_directory_with_one_model_resolves_to_it(tmp_path: Path) -> None:
    expected = write_model(tmp_path)

    assert resolve_model_json(tmp_path) == expected


def test_directory_with_two_models_asks_for_a_specific_one(tmp_path: Path) -> None:
    write_model(tmp_path, "A.model3.json")
    write_model(tmp_path, "B.model3.json")

    with pytest.raises(ModelNotFound, match="多个模型"):
        resolve_model_json(tmp_path)


def test_empty_directory_is_reported(tmp_path: Path) -> None:
    with pytest.raises(ModelNotFound, match="没有模型 json"):
        resolve_model_json(tmp_path)


def test_json_path_is_used_as_is(tmp_path: Path) -> None:
    expected = write_model(tmp_path)

    assert resolve_model_json(expected) == expected


def test_cubism_21_json_is_recognised(tmp_path: Path) -> None:
    expected = write_model(tmp_path, "miku.model.json")

    assert resolve_model_json(tmp_path) == expected


def test_a_random_file_is_rejected_with_a_hint(tmp_path: Path) -> None:
    other = tmp_path / "readme.txt"
    other.write_text("hi", encoding="utf-8")

    with pytest.raises(ModelNotFound, match="不是模型 json"):
        resolve_model_json(other)


def test_missing_path_is_reported(tmp_path: Path) -> None:
    with pytest.raises(ModelNotFound, match="不存在"):
        resolve_model_json(tmp_path / "models" / "hiyori")


def test_is_model_json_only_accepts_files(tmp_path: Path) -> None:
    write_model(tmp_path)

    assert is_model_json(tmp_path) is False
    assert is_model_json(tmp_path / "Hiyori.model3.json") is True
