"""把配置里的模型路径解析成具体的模型 json。

``.env`` 里写目录还是写 json 文件都合理（前者是"模型文件夹"的直觉写法，
后者更精确），所以两种都接受，判定规则集中在这里，渲染进程不再自己猜。
"""

from __future__ import annotations

from pathlib import Path

#: Cubism 4/5 用 .model3.json，Cubism 2.1 用 .model.json。两种都要认。
MODEL_JSON_SUFFIXES = (".model3.json", ".model.json")


class ModelNotFound(Exception):
    """配置里的路径找不到可用的模型 json。"""


def is_model_json(path: Path) -> bool:
    """这个路径是不是一个模型 json 文件。"""
    return path.is_file() and path.name.endswith(MODEL_JSON_SUFFIXES)


def resolve_model_json(path: Path) -> Path:
    """把配置里的路径解析成一个模型 json。

    Args:
        path: 模型目录，或直接指向模型 json。

    Returns:
        Path: 可直接交给 ``LAppModel.LoadModelJson()`` 的路径。

    Raises:
        ModelNotFound: 路径不存在、不是模型 json、目录里没有模型，或目录里有多个
            候选。报错信息里会写清该怎么改配置，而不是只丢一句"找不到"。
    """
    if is_model_json(path):
        return path

    if path.is_file():
        raise ModelNotFound(
            f"{path} 不是模型 json（需要以 {' 或 '.join(MODEL_JSON_SUFFIXES)} 结尾）"
        )

    if path.is_dir():
        candidates = sorted(item for item in path.iterdir() if is_model_json(item))
        if not candidates:
            raise ModelNotFound(
                f"{path} 下没有模型 json（找过 {'、'.join(MODEL_JSON_SUFFIXES)}）"
            )
        if len(candidates) > 1:
            names = "、".join(item.name for item in candidates)
            raise ModelNotFound(
                f"{path} 下有多个模型（{names}），LIVE2D_MODEL_PATH 请直接指到其中一个"
            )
        return candidates[0]

    raise ModelNotFound(f"模型路径不存在：{path}")
