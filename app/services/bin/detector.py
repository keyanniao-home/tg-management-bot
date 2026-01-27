import re
from typing import Optional
from loguru import logger
from sqlmodel import Session, select
from app.database.connection import engine
from app.models.bin_config import BinConfig
from app.utils.markdown import escape_markdown_v2


class BinDetector:
    """BIN消息检测器"""

    # 6位及以上连续数字的正则
    BIN_PATTERN = re.compile(r'\d{6,}')

    @staticmethod
    def contains_possible_bin(text: str) -> bool:
        """
        检测消息是否包含可能的BIN

        Args:
            text: 消息文本

        Returns:
            True如果包含6位及以上连续数字
        """
        if not text or len(text) > 1000:
            return False

        return bool(BinDetector.BIN_PATTERN.search(text))

    @staticmethod
    def is_monitoring_enabled(session: Session, group_db_id: int, topic_id: int) -> bool:
        """
        检查话题是否启用BIN监听

        Args:
            session: 数据库会话
            group_db_id: 群组数据库ID（GroupConfig.id）
            topic_id: 话题ID

        Returns:
            True如果已启用监听
        """
        config = session.exec(
            select(BinConfig).where(
                BinConfig.group_id == group_db_id,
                BinConfig.topic_id == topic_id,
                BinConfig.enabled == True
            )
        ).first()
        return config is not None

    @staticmethod
    async def process_bin_message(
        bot,
        chat_id: int,
        group_db_id: int,
        topic_id: int,
        message_id: int,
        message_text: str,
        sender_user_id: Optional[int],
        sender_username: Optional[str],
        sender_chat_id: Optional[int]
    ):
        """
        处理BIN消息（异步）- 独立session版本

        注意：此函数在异步任务中执行，不应复用events.py中的session

        Args:
            bot: Telegram Bot实例
            chat_id: 聊天ID（用于发送回复消息）
            group_db_id: 数据库群组ID
            topic_id: 话题ID
            message_id: 原始消息ID
            message_text: 消息文本
            sender_user_id: 发送者用户ID
            sender_username: 发送者用户名
            sender_chat_id: 发送者聊天ID（频道消息）
        """
        from app.services.bin.parser import BinParser
        from app.services.bin.storage import BinStorage
        import asyncio

        # 创建新的session（重要！）
        with Session(engine) as session:
            try:
                # 获取配置（包含自定义prompt）
                config = session.exec(
                    select(BinConfig).where(
                        BinConfig.group_id == group_db_id,
                        BinConfig.topic_id == topic_id
                    )
                ).first()

                if not config or not config.enabled:
                    logger.debug(f"BIN监听未启用: group={group_db_id}, topic={topic_id}")
                    return

                custom_prompt = config.ai_prompt

                # 调用AI解析
                result = await BinParser.parse_bin_message(message_text, custom_prompt)

                if not result or not result.cards:
                    logger.debug(f"未识别到有效BIN: message={message_id}")
                    return

                # 过滤掉没有网站信息的卡片（说明不是真正的BIN信息）
                valid_cards = []
                for card in result.cards:
                    # 检查是否有有效的网站（name和domain都不为空）
                    has_valid_site = any(
                        site.name and site.name.strip() and site.domain and site.domain.strip()
                        for site in card.sites
                    )
                    if has_valid_site:
                        valid_cards.append(card)
                    else:
                        logger.debug(f"跳过无网站信息的卡片: rule={card.rule}")

                # 如果过滤后没有有效卡片，说明这不是BIN消息
                if not valid_cards:
                    logger.debug(f"消息不包含有效的BIN信息（无网站）: message={message_id}")
                    return

                # 更新result的cards为过滤后的列表
                result.cards = valid_cards

                # 保存到数据库（异步调用）
                saved_count, duplicates = await BinStorage.save_bin_cards(
                    session=session,
                    group_db_id=group_db_id,
                    topic_id=topic_id,
                    message_id=message_id,
                    sender_user_id=sender_user_id,
                    sender_username=sender_username,
                    sender_chat_id=sender_chat_id,
                    original_text=message_text,
                    cards=result.cards
                )

                logger.info(f"成功保存 {saved_count} 张BIN卡: group={group_db_id}, topic={topic_id}, message={message_id}")

                # 如果全部重复，提示用户
                if saved_count == 0 and duplicates:
                    reply_text = "ℹ️ *BIN信息已存在*\n\n"
                    reply_text += "以下规则\\+域名组合已被收录：\n\n"
                    for dup in duplicates[:5]:
                        dup_escaped = escape_markdown_v2(dup)
                        reply_text += f"• `{dup_escaped}`\n"
                    if len(duplicates) > 5:
                        reply_text += f"\n\\.\\.\\.及其他 {len(duplicates) - 5} 个"
                else:
                    # 构建回复消息
                    reply_text = "✅ *BIN信息已保存*\n\n"
                    reply_text += f"识别到 *{saved_count}* 张BIN卡：\n\n"

                for i, card in enumerate(result.cards[:3], 1):  # 最多显示前3张
                    # Markdown转义
                    rule_escaped = escape_markdown_v2(card.rule)
                    reply_text += f"{i}\\. `{rule_escaped}`\n"

                    if card.sites:
                        site_names = ", ".join([s.name for s in card.sites[:3]])
                        if len(card.sites) > 3:
                            site_names += f" 等{len(card.sites)}个网站"
                        site_names_escaped = escape_markdown_v2(site_names)
                        reply_text += f"   网站: {site_names_escaped}\n"

                    if card.ip:
                        ip_escaped = escape_markdown_v2(card.ip)
                        reply_text += f"   IP: {ip_escaped}\n"
                    reply_text += "\n"

                    if saved_count > 3:
                        reply_text += f"\\.\\.\\.及其他 {saved_count - 3} 张卡\n\n"

                    # 如果有部分重复，追加提示
                    if duplicates:
                        reply_text += f"\n⚠️ {len(duplicates)} 个重复组合已跳过\n\n"

                    reply_text += "使用 /bin\\_search 搜索查看详情"

                # 回复原消息
                reply_msg = await bot.send_message(
                    chat_id=chat_id,
                    text=reply_text,
                    reply_to_message_id=message_id,
                    message_thread_id=topic_id,
                    parse_mode="MarkdownV2"
                )

                await asyncio.sleep(30)
                try:
                    await bot.delete_message(chat_id=chat_id, message_id=reply_msg.message_id)
                    logger.debug(f"已删除BIN回复消息: {reply_msg.message_id}")
                except Exception as e:
                    logger.warning(f"删除BIN回复消息失败: {e}")

            except Exception as e:
                logger.exception(f"处理BIN消息失败: {e}")
                # 不抛出异常，避免影响主流程
