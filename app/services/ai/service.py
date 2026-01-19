"""
AI 服务基础模块

使用 OpenAI 兼容接口进行结构化输出
"""
import asyncio
from typing import Optional, TypeVar, Type
from openai import AsyncOpenAI
from pydantic import BaseModel
from loguru import logger

from app.config.settings import settings


T = TypeVar('T', bound=BaseModel)


class AIService:
    """AI 服务单例"""

    _instance: Optional['AIService'] = None
    _client: Optional[AsyncOpenAI] = None

    def __new__(cls):
        if cls._instance is None:
            cls._instance = super().__new__(cls)
        return cls._instance

    def __init__(self):
        """初始化 AI 服务"""
        if not settings.is_ai_configured:
            logger.warning("AI 功能未配置，相关功能将不可用")
            return

        # 初始化 OpenAI 客户端
        self._client = AsyncOpenAI(
            base_url=settings.ai_base_url,
            api_key=settings.ai_api_key
        )

        logger.info(f"✅ AI 服务已初始化 - 模型: {settings.ai_model_id}")

    def is_configured(self) -> bool:
        """检查是否已配置"""
        return self._client is not None

    async def generate_text(
        self,
        prompt: str,
        system_prompt: Optional[str] = None,
        temperature: float = 0.7,
        max_tokens: int = 2000
    ) -> str:
        """
        生成自然语言文本

        Args:
            prompt: 用户提示词
            system_prompt: 系统提示词
            temperature: 温度参数
            max_tokens: 最大token数

        Returns:
            生成的文本
        """
        if not self.is_configured():
            raise RuntimeError("AI 服务未配置")

        try:
            messages = []
            if system_prompt:
                messages.append({"role": "system", "content": system_prompt})
            messages.append({"role": "user", "content": prompt})

            response = await self._client.chat.completions.create(
                model=settings.ai_model_id,
                messages=messages,
                temperature=temperature,
                max_tokens=max_tokens
            )

            return response.choices[0].message.content

        except Exception as e:
            logger.error(f"AI 生成文本失败: {e}")
            raise

    async def generate_structured(
        self,
        prompt: str,
        response_model: Type[T],
        system_prompt: Optional[str] = None,
        temperature: float = 0.7,
        max_tokens: int = 2000
    ) -> T:
        """
        生成结构化数据（使用 Pydantic 模型）

        Args:
            prompt: 用户提示词
            response_model: 响应的 Pydantic 模型类
            system_prompt: 系统提示词
            temperature: 温度参数
            max_tokens: 最大token数

        Returns:
            结构化数据对象
        """
        if not self.is_configured():
            raise RuntimeError("AI 服务未配置")

        try:
            messages = []
            if system_prompt:
                messages.append({"role": "system", "content": system_prompt})
            messages.append({"role": "user", "content": prompt})

            # 使用 OpenAI 的结构化输出功能
            # 从 Pydantic 模型生成 JSON Schema
            schema = response_model.model_json_schema()

            response = await self._client.chat.completions.create(
                model=settings.ai_model_id,
                messages=messages,
                response_format={
                    "type": "json_schema",
                    "json_schema": {
                        "name": response_model.__name__,
                        "schema": schema,
                        "strict": True
                    }
                },
                temperature=temperature,
                max_tokens=max_tokens
            )

            # 解析返回的 JSON 为 Pydantic 模型
            import json
            json_content = response.choices[0].message.content
            data = json.loads(json_content)
            return response_model.model_validate(data)

        except Exception as e:
            logger.error(f"AI 生成结构化数据失败: {e}")
            raise


# 全局单例
ai_service = AIService()
