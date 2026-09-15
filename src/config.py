"""配置加载与校验。

配置只走 .env（见 AGENTS.md 硬约束 4）。这一层故意做成"宽松加载、严格使用"：
缺 .env 或缺 Key 时不在构造阶段崩，等真正要调用 LLM 之前再由
``require_llm_credentials()`` 给出能照着做的报错。
"""

from __future__ import annotations

from typing import Literal

from pydantic import Field, field_validator
from pydantic_settings import BaseSettings, SettingsConfigDict

LLMProvider = Literal["deepseek", "openai_compatible"]
TTSBackendName = Literal["edge"]


class Settings(BaseSettings):
    """全部配置项。字段名与 .env 里的键一一对应（大小写不敏感）。"""

    model_config = SettingsConfigDict(
        env_file=".env",
        env_file_encoding="utf-8",
        extra="ignore",
        case_sensitive=False,
    )

    # LLM
    llm_provider: LLMProvider = "deepseek"
    llm_model: str = "deepseek-chat"
    llm_api_key: str = ""
    llm_base_url: str = ""
    llm_temperature: float = Field(default=1.0, ge=0.0, le=2.0)

    # TTS
    tts_backend: TTSBackendName = "edge"
    tts_edge_voice: str = "zh-CN-XiaoxiaoNeural"
    tts_edge_rate: str = "+0%"

    # Live2D
    live2d_model_path: str = "models/hiyori"
    live2d_window_width: int = Field(default=400, gt=0)
    live2d_window_height: int = Field(default=600, gt=0)

    # 其他
    log_level: str = "INFO"

    @field_validator("llm_model", "tts_edge_voice", "live2d_model_path")
    @classmethod
    def _not_blank(cls, value: str) -> str:
        """这几个字段是空串时一定跑不起来，不如在加载时就拦住。"""
        if not value.strip():
            raise ValueError("不能为空")
        return value.strip()

    def require_llm_credentials(self) -> None:
        """调用 LLM 之前的前置检查。

        Raises:
            RuntimeError: 缺少 API Key，或选了 OpenAI 兼容端点却没填 Base URL。
        """
        if not self.llm_api_key.strip():
            raise RuntimeError(
                f"缺少 LLM_API_KEY：请在 .env 里填入 {self.llm_provider} 的 API Key"
            )
        if self.llm_provider == "openai_compatible" and not self.llm_base_url.strip():
            raise RuntimeError("LLM_PROVIDER=openai_compatible 时必须同时填 LLM_BASE_URL")
