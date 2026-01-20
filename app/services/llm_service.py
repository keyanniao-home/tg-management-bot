"""
LLM Service for Message Summarization
Supports OpenAI-compatible APIs
"""
import asyncio
from typing import Optional, List, Dict
from openai import AsyncOpenAI, OpenAIError
from loguru import logger
from app.config.settings import settings


class LLMService:
    """LLM服务，用于消息总结"""
    
    def __init__(self):
        self.client: Optional[AsyncOpenAI] = None
        self.is_enabled = settings.is_llm_configured
        
        if self.is_enabled:
            self.client = AsyncOpenAI(
                api_key=settings.llm_api_key,
                base_url=settings.llm_base_url
            )
            logger.info(f"LLM Service initialized with base_url: {settings.llm_base_url}, model: {settings.llm_model}")
        else:
            logger.info("LLM Service is disabled (not configured)")
   
    async def summarize_messages(
        self, 
        messages: List[Dict[str, str]],
        context: Optional[str] = None,
        max_tokens: int = 1000
    ) -> Optional[Dict[str, any]]:
        """
        总结消息列表
        
        Args:
            messages: 消息列表，每条消息格式为 {"sender": "用户名", "text": "消息内容", "time": "时间"}
            context: 额外上下文信息
            max_tokens: 最大token数
            
        Returns:
            {"summary": "总结文本", "tokens_used": 估计token数} 或 None（如果失败）
        """
        if not self.is_enabled:
            logger.warning("LLM Service not configured, cannot summarize")
            return None
            
        if not messages:
            return {"summary": "没有消息需要总结", "tokens_used": 0}
        
        try:
            # 构建消息内容
            message_text = "\n".join([
                f"[{msg.get('time', '')}] {msg.get('sender', '未知用户')}: {msg.get('text', '')}"
                for msg in messages
            ])
            
            # 限制消息长度（避免超token）
            max_content_chars = 8000
            if len(message_text) > max_content_chars:
                message_text = message_text[:max_content_chars] + "\n... (消息过多，已截断)"
            
            # 构建提示词
            system_prompt = """你是一个专业的群聊消息总结助手。
请对以下技术群的聊天记录进行简洁、准确的总结。
总结要求：
1. 使用中文
2. 按主题分类归纳讨论的要点
3. 突出重要信息（如技术方案、资源分享、问题解答等）
4. 保持简洁，控制在300字以内
5. 直接输出Markdown格式文本，使用bullet points（-）、粗体（**文本**）等基础语法
6. 不要使用代码块（```）包裹输出内容，Telegram会自动渲染Markdown"""

            user_prompt = f"""请总结以下聊天记录：

{message_text}

{f'背景信息：{context}' if context else ''}"""

            # 调用LLM
            response = await self.client.chat.completions.create(
                model=settings.llm_model,
                messages=[
                    {"role": "system", "content": system_prompt},
                    {"role": "user", "content": user_prompt}
                ],
                max_tokens=max_tokens,
                temperature=0.7
            )
            
            summary = response.choices[0].message.content
            tokens_used = response.usage.total_tokens if response.usage else 0
            
            logger.info(f"Generated summary, tokens used: {tokens_used}")
            
            return {
                "summary": summary,
                "tokens_used": tokens_used,
                "model": settings.llm_model
            }
            
        except OpenAIError as e:
            logger.error(f"OpenAI API error: {e}")
            return None
        except Exception as e:
            logger.error(f"Error generating summary: {e}")
            return None
    
    async def generate_daily_digest(
        self,
        messages: List[Dict[str, str]],
        date_str: str,
        stats: Optional[Dict] = None
    ) -> Optional[Dict[str, any]]:
        """
        生成每日摘要
        
        Args:
            messages: 消息列表
            date_str: 日期字符串，如 "2026-01-16"
            stats: 统计数据 {"total_messages": 100, "active_users": 20, ...}
            
        Returns:
            {"summary": "摘要文本", "tokens_used": token数} 或 None
        """
        if not self.is_enabled:
            return None
            
        context = f"这是{date_str}的群聊记录"
        if stats:
            context += f"，共{stats.get('total_messages', 0)}条消息，{stats.get('active_users', 0)}位活跃成员"
        
        # 使用更大的token限制用于每日摘要
        return await self.summarize_messages(messages, context=context, max_tokens=1500)
    
    async def health_check(self) -> bool:
        """检查LLM服务是否可用"""
        if not self.is_enabled:
            return False
        
        try:
            # 发送一个简单的测试请求
            response = await self.client.chat.completions.create(
                model=settings.llm_model,
                messages=[{"role": "user", "content": "Hello"}],
                max_tokens=5
            )
            return True
        except Exception as e:
            logger.error(f"LLM health check failed: {e}")
            return False


# 全局LLM服务实例
llm_service = LLMService()
