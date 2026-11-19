"""对话消息：送给 LLM 之前拼好的上下文单元。"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Literal

#: 消息角色。M1 只有这三种。
Role = Literal["system", "user", "assistant"]


@dataclass(frozen=True, slots=True)
class Message:
    """一条对话消息。

    上层（runtime）负责拼上下文，本类型只负责承载。

    Attributes:
        role: 消息角色。
        content: 消息正文。

    Example:
        ```python
        Message(role="user", content="在吗").to_payload()
        # {'role': 'user', 'content': '在吗'}
        ```
    """

    role: Role
    content: str

    def to_payload(self) -> dict[str, str]:
        """转成 LiteLLM 接受的字典形式。

        Returns:
            恰含 ``role`` 与 ``content`` 两个键的字典。

        Example:
            ```python
            Message(role="system", content="你是角色").to_payload()
            # {'role': 'system', 'content': '你是角色'}
            ```
        """
        return {"role": self.role, "content": self.content}
