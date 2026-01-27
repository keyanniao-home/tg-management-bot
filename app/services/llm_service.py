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
            max_content_chars = 18000
            if len(message_text) > max_content_chars:
                message_text = message_text[:max_content_chars] + "\n... (消息过多，已截断)"
            
            # 构建提示词
            system_prompt = """你是一个专业的群聊消息总结助手，擅长从大量对话中提取关键信息并结构化呈现。

**核心任务**：分析群聊记录，生成清晰、有价值的总结,让用户快速了解错过的讨论内容。

**总结原则**：
1. **智能筛选**：自动忽略闲聊、表情、无意义的短消息（如"哈哈"、"好的"、"+1"等）
2. **主题聚合**：识别并归类不同的讨论主题，即使话题交叉出现也要准确分组
3. **人物追踪**：标注每个话题的主要参与者和关键贡献
4. **价值优先**：突出问题、解决方案、决策、资源链接、时间节点等高价值信息

**输出格式**：
- 使用中文
- 采用Markdown格式（bullet points用"-"，粗体用**文本**）
- 不使用代码块包裹（```），让Telegram直接渲染
- 控制在400字以内，确保简洁但信息完整

**结构模板**：
📊 **消息概览**：共X条消息，X人参与

🔥 **核心话题**
- **[话题1名称]**：简述讨论内容（主要参与者：@用户A、@用户B）
  - 关键点1
  - 关键点2（如有解决方案或结论）
  
💡 **重要信息**
- 资源/链接/文件分享
- 待办事项或决策
- 时间安排

👥 **活跃成员**：@用户A（主要讨论X）、@用户B（分享了Y）

⚠️ **需要关注**：未解决的问题或后续事项（如有）
"""

            context_info = f"\n\n背景信息：{context}" if context else ""
            user_prompt = f"""请分析以下群聊记录并生成结构化总结：

{message_text}

**分析要点**：
1. 识别出所有不同的讨论主题（技术问题、方案讨论、资源分享、日常交流等）
2. 过滤掉纯闲聊、重复确认、无实质内容的消息
3. 标注每个话题的关键参与者
4. 提取可执行信息（链接、时间、待办等）
5. 如果有问答，明确标出问题是否得到解答

直接输出总结，无需额外说明。{context_info}"""

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
