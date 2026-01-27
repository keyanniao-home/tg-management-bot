from datetime import datetime
from telegram import Update, InlineKeyboardButton, InlineKeyboardMarkup
from telegram.ext import ContextTypes
from sqlmodel import Session, select, func
from loguru import logger
import asyncio
import random

from app.database.connection import engine
from app.models.group import GroupConfig
from app.models.bin_config import BinConfig
from app.models.bin_card import BinCard
from app.models.bin_site import BinSite
from app.handlers.commands import is_admin
from app.utils.reply_handler_manager import reply_handler_manager
from app.services.bin.search import BinSearchService
from app.utils.markdown import escape_markdown_v2


async def bin_monitor_command(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """
    /bin_monitor - 启用/禁用当前话题的BIN监听

    用法：
    /bin_monitor enable         - 启用监听
    /bin_monitor disable        - 禁用监听
    /bin_monitor status         - 查看状态
    /bin_monitor set_prompt     - 设置自定义AI提示词（通过回复）
    """

    # 权限检查
    if not await is_admin(update):
        await update.message.reply_text("❌ 此命令仅限管理员使用")
        return

    # 必须在话题中使用
    if not update.message.is_topic_message:
        await update.message.reply_text(
            "❌ 此命令只能在话题中使用\n\n"
            "请在需要监听BIN的话题内执行此命令"
        )
        return

    topic_id = update.message.message_thread_id
    chat_id = update.effective_chat.id

    # 解析参数
    if not context.args:
        # 显示帮助
        help_text = (
            "**BIN监听管理**\n\n"
            "用法：\n"
            "`/bin_monitor enable` - 启用当前话题的BIN监听\n"
            "`/bin_monitor disable` - 禁用监听\n"
            "`/bin_monitor status` - 查看监听状态\n"
            "`/bin_monitor set_prompt` - 设置自定义AI提示词\n\n"
            "启用后，Bot会自动识别话题中的BIN消息并保存"
        )
        await update.message.reply_text(help_text, parse_mode="Markdown")
        return

    action = context.args[0].lower()

    with Session(engine) as session:
        # 获取群组配置
        group = session.exec(
            select(GroupConfig).where(GroupConfig.group_id == chat_id)
        ).first()

        if not group:
            await update.message.reply_text("❌ 群组未初始化，请先使用 /init")
            return

        # 获取或创建BIN配置
        config = session.exec(
            select(BinConfig).where(
                BinConfig.group_id == group.id,
                BinConfig.topic_id == topic_id
            )
        ).first()

        if action == "enable":
            if not config:
                config = BinConfig(
                    group_id=group.id,
                    topic_id=topic_id,
                    enabled=True
                )
                session.add(config)
            else:
                config.enabled = True
                config.updated_at = datetime.utcnow()

            session.commit()
            await update.message.reply_text(
                "✅ BIN监听已启用\n\n"
                f"话题ID: `{topic_id}`\n"
                "Bot将自动识别包含BIN的消息",
                parse_mode="Markdown"
            )

        elif action == "disable":
            if config:
                config.enabled = False
                config.updated_at = datetime.utcnow()
                session.commit()
                await update.message.reply_text("✅ BIN监听已禁用")
            else:
                await update.message.reply_text("ℹ️ 此话题未启用BIN监听")

        elif action == "status":
            if config and config.enabled:
                # 转换为中国时区（UTC+8）
                from datetime import timedelta
                cst_time = config.created_at + timedelta(hours=8)
                status_text = (
                    "**BIN监听状态**\n\n"
                    f"话题ID: `{topic_id}`\n"
                    f"状态: ✅ 已启用\n"
                    f"启用时间: {cst_time.strftime('%Y-%m-%d %H:%M')}\n"
                )
                if config.ai_prompt:
                    status_text += "\n使用自定义AI提示词"
                else:
                    status_text += "\n使用默认AI提示词"
            else:
                status_text = (
                    "**BIN监听状态**\n\n"
                    f"话题ID: `{topic_id}`\n"
                    f"状态: ❌ 未启用\n\n"
                    "使用 `/bin_monitor enable` 启用监听"
                )

            await update.message.reply_text(status_text, parse_mode="Markdown")

        elif action == "set_prompt":
            # TODO: 实现自定义prompt设置
            await update.message.reply_text(
                "ℹ️ 自定义提示词功能开发中\n\n"
                "当前使用默认提示词"
            )

        else:
            await update.message.reply_text(
                f"❌ 未知操作: {action}\n\n"
                "使用 `/bin_monitor` 查看帮助"
            )


async def bin_search_command(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """
    /bin_search - 搜索BIN信息
    """

    keyboard = [
        [InlineKeyboardButton("🔢 按卡头搜索", callback_data="bin_search_rule")],
        [InlineKeyboardButton("🌐 按网站名搜索", callback_data="bin_search_site")],
        [InlineKeyboardButton("🔗 按域名搜索", callback_data="bin_search_domain")],
        [InlineKeyboardButton("👤 按发送者搜索", callback_data="bin_search_sender")]
    ]

    menu_msg = await update.message.reply_text(
        "🔍 **BIN信息搜索**\n\n请选择搜索方式：",
        reply_markup=InlineKeyboardMarkup(keyboard),
        parse_mode="Markdown"
    )

    # 30秒后自动删除用户的命令消息和搜索菜单
    asyncio.create_task(_delete_message_later(context.bot, update.effective_chat.id, update.message.message_id, 300))
    asyncio.create_task(_delete_message_later(context.bot, update.effective_chat.id, menu_msg.message_id, 300))


async def bin_browse_command(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """
    /bin_browse - 浏览所有BIN信息
    """
    chat_id = update.effective_chat.id

    with Session(engine) as session:
        group = session.exec(
            select(GroupConfig).where(GroupConfig.group_id == chat_id)
        ).first()

        if not group:
            await update.message.reply_text("❌ 群组未初始化")
            return

        # 显示排序选择菜单
        keyboard = [
            [
                InlineKeyboardButton("🕒 按时间", callback_data="bin_browse_time_desc_1"),
                InlineKeyboardButton("🔢 按卡头", callback_data="bin_browse_rule_desc_1")
            ],
            [
                InlineKeyboardButton("👤 按发送者", callback_data="bin_browse_sender_desc_1")
            ]
        ]

        menu_msg = await update.message.reply_text(
            "📚 **BIN信息浏览**\n\n"
            "请选择排序方式（默认降序）：\n\n"
            "🕒 按时间 - 最新的在前\n"
            "🔢 按卡头 - 按BIN规则排序\n"
            "👤 按发送者 - 按用户名排序",
            reply_markup=InlineKeyboardMarkup(keyboard),
            parse_mode="Markdown"
        )

        # 300秒后自动删除命令消息和菜单
        asyncio.create_task(_delete_message_later(context.bot, chat_id, update.message.message_id, 300))
        asyncio.create_task(_delete_message_later(context.bot, chat_id, menu_msg.message_id, 300))


async def bin_search_callback(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """处理BIN搜索相关回调"""
    query = update.callback_query
    await query.answer()

    data = query.data

    if data == "bin_search_rule":
        bot_msg = await query.edit_message_text(
            "🔢 **按卡头搜索**\n\n"
            "请回复此消息，输入卡号前缀（如：453201）：",
            parse_mode="Markdown"
        )
        reply_handler_manager.register(
            bot_message_id=bot_msg.message_id,
            chat_id=update.effective_chat.id,
            handler=handle_bin_rule_search_input,
            handler_name="bin_rule_search"
        )
        # 30秒后自动删除提示消息
        asyncio.create_task(_delete_message_later(context.bot, update.effective_chat.id, bot_msg.message_id, 300))

    elif data == "bin_search_site":
        bot_msg = await query.edit_message_text(
            "🌐 **按网站名搜索**\n\n"
            "请回复此消息，输入网站名称（如：Netflix）：",
            parse_mode="Markdown"
        )
        reply_handler_manager.register(
            bot_message_id=bot_msg.message_id,
            chat_id=update.effective_chat.id,
            handler=handle_bin_site_search_input,
            handler_name="bin_site_search"
        )
        # 30秒后自动删除提示消息
        asyncio.create_task(_delete_message_later(context.bot, update.effective_chat.id, bot_msg.message_id, 300))

    elif data == "bin_search_domain":
        bot_msg = await query.edit_message_text(
            "🔗 **按域名搜索**\n\n"
            "请回复此消息，输入域名（如：netflix.com）：",
            parse_mode="Markdown"
        )
        reply_handler_manager.register(
            bot_message_id=bot_msg.message_id,
            chat_id=update.effective_chat.id,
            handler=handle_bin_domain_search_input,
            handler_name="bin_domain_search"
        )
        # 30秒后自动删除提示消息
        asyncio.create_task(_delete_message_later(context.bot, update.effective_chat.id, bot_msg.message_id, 300))

    elif data == "bin_search_sender":
        bot_msg = await query.edit_message_text(
            "👤 **按发送者搜索**\n\n"
            "请回复此消息，输入用户名（@username）或用户ID：",
            parse_mode="Markdown"
        )
        reply_handler_manager.register(
            bot_message_id=bot_msg.message_id,
            chat_id=update.effective_chat.id,
            handler=handle_bin_sender_search_input,
            handler_name="bin_sender_search"
        )
        # 30秒后自动删除提示消息
        asyncio.create_task(_delete_message_later(context.bot, update.effective_chat.id, bot_msg.message_id, 300))

    elif data == "bin_browse_back":
        # 返回浏览菜单（精确匹配，必须在startswith之前）
        keyboard = [
            [
                InlineKeyboardButton("🕒 按时间", callback_data="bin_browse_time_desc_1"),
                InlineKeyboardButton("🔢 按卡头", callback_data="bin_browse_rule_desc_1")
            ],
            [
                InlineKeyboardButton("👤 按发送者", callback_data="bin_browse_sender_desc_1")
            ]
        ]
        await query.edit_message_text(
            "📚 **BIN信息浏览**\n\n"
            "请选择排序方式（默认降序）：\n\n"
            "🕒 按时间 - 最新的在前\n"
            "🔢 按卡头 - 按BIN规则排序\n"
            "👤 按发送者 - 按用户名排序",
            reply_markup=InlineKeyboardMarkup(keyboard),
            parse_mode="Markdown"
        )

    elif data.startswith("bin_browse_"):
        # 处理浏览回调: bin_browse_{order_by}_{order_dir}_{page}
        await handle_bin_browse_callback(update, context)

    elif data.startswith("bin_result_"):
        # 解析回调数据: bin_result_{bin_id} 或 bin_result_{bin_id}_browse_{order_by}_{order_dir}_{page}
        parts = data.split("_")
        bin_id = int(parts[2])

        # 检查是否从浏览进入
        source_context = None
        if len(parts) > 3 and parts[3] == "browse":
            # 从浏览进入，保存上下文信息
            source_context = {
                "source": "browse",
                "order_by": parts[4],
                "order_dir": parts[5],
                "page": parts[6]
            }

        await show_bin_detail(update, context, bin_id, source_context)

    elif data.startswith("bin_generate_"):
        bin_id = int(data.split("_")[2])
        await generate_card_callback(update, context, bin_id)

    elif data == "bin_search_back":
        # 返回搜索菜单（编辑当前消息）
        keyboard = [
            [InlineKeyboardButton("🔢 按卡头搜索", callback_data="bin_search_rule")],
            [InlineKeyboardButton("🌐 按网站名搜索", callback_data="bin_search_site")],
            [InlineKeyboardButton("🔗 按域名搜索", callback_data="bin_search_domain")],
            [InlineKeyboardButton("👤 按发送者搜索", callback_data="bin_search_sender")]
        ]
        await query.edit_message_text(
            "🔍 **BIN信息搜索**\n\n请选择搜索方式：",
            reply_markup=InlineKeyboardMarkup(keyboard),
            parse_mode="Markdown"
        )


# 删除消息辅助函数
async def _delete_message_later(bot, chat_id: int, message_id: int, delay: int = 30):
    """延迟删除消息"""
    await asyncio.sleep(delay)
    try:
        await bot.delete_message(chat_id=chat_id, message_id=message_id)
        logger.debug(f"已删除消息: {message_id}")
    except Exception as e:
        logger.warning(f"删除消息失败: {e}")


def calculate_luhn(card_number: str) -> str:
    """
    计算Luhn校验码

    Args:
        card_number: 不含校验位的卡号

    Returns:
        完整卡号（包含校验位）
    """
    digits = [int(d) for d in card_number]

    # 从右往左，每隔一位乘以2
    for i in range(len(digits) - 1, -1, -2):
        digits[i] *= 2
        if digits[i] > 9:
            digits[i] -= 9

    total = sum(digits)
    check_digit = (10 - (total % 10)) % 10

    return card_number + str(check_digit)


def generate_card_from_rule(rule: str) -> str:
    """
    根据BIN规则生成卡片

    Args:
        rule: BIN规则，如 "453201|12|28|xxx" 或 "37936303|xx|xx|xxxx"

    Returns:
        生成的完整卡片信息，格式: "卡号|月|年|CVV"
    """
    parts = rule.split('|')
    if len(parts) != 4:
        return rule  # 格式不正确，返回原规则

    bin_part, month_part, year_part, cvv_part = parts

    # 1. 处理卡号部分
    # 将x替换为随机数字，保留最后一位用于Luhn校验
    card_number = ""
    for char in bin_part[:-1]:  # 除了最后一位
        if char.lower() == 'x':
            card_number += str(random.randint(0, 9))
        else:
            card_number += char

    # 最后一位：如果是x则先用0占位，如果是数字则保留
    if bin_part[-1].lower() == 'x':
        card_number += '0'  # 临时占位
    else:
        card_number += bin_part[-1]

    # 计算并替换Luhn校验位
    card_number = calculate_luhn(card_number[:-1])

    # 2. 处理年份和月份（确保不过期：从当前月到2030年12月）
    now = datetime.now()
    current_year = now.year % 100  # 当前年份后两位
    current_month = now.month
    max_year = 30  # 2030年

    if year_part.lower() == 'xx' and month_part.lower() == 'xx':
        # 两者都是xx：随机生成不过期的年月
        # 年份范围：当前年到2030年
        year_offset = random.randint(0, max_year - current_year)

        if year_offset == 0:
            # 当前年：月份从当前月到12月
            month = str(random.randint(current_month, 12)).zfill(2)
        else:
            # 未来年：月份从1月到12月
            month = str(random.randint(1, 12)).zfill(2)

        year = str((current_year + year_offset) % 100).zfill(2)

    elif year_part.lower() == 'xx':
        # 只有年份是xx，月份已指定
        month = month_part
        specified_month = int(month_part)

        # 如果指定月份小于当前月，必须是未来年
        if specified_month < current_month:
            year_offset = random.randint(1, max_year - current_year)  # 未来年
        else:
            year_offset = random.randint(0, max_year - current_year)  # 当前年或未来

        year = str((current_year + year_offset) % 100).zfill(2)

    elif month_part.lower() == 'xx':
        # 只有月份是xx，年份已指定
        year = year_part
        year_value = int(year_part)

        # 计算年份偏移
        if year_value >= current_year:
            year_offset = year_value - current_year
        else:
            year_offset = (100 + year_value - current_year)

        if year_offset == 0:
            # 当前年：月份从当前月到12月
            month = str(random.randint(current_month, 12)).zfill(2)
        else:
            # 未来年：月份从1月到12月
            month = str(random.randint(1, 12)).zfill(2)

    else:
        # 年月都已指定，直接使用
        month = month_part
        year = year_part

    # 4. 处理CVV
    cvv_length = len(cvv_part)
    cvv = ''.join([str(random.randint(0, 9)) for _ in range(cvv_length)])

    return f"{card_number}|{month}|{year}|{cvv}"


# 搜索输入处理器
async def handle_bin_rule_search_input(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """处理卡头搜索输入"""
    search_keyword = update.message.text.strip()

    if not search_keyword.isdigit():
        await update.message.reply_text("❌ 请输入数字")
        return

    chat_id = update.effective_chat.id

    with Session(engine) as session:
        group = session.exec(
            select(GroupConfig).where(GroupConfig.group_id == chat_id)
        ).first()

        if not group:
            await update.message.reply_text("❌ 群组未初始化")
            reply_handler_manager.unregister(update.message.reply_to_message.message_id)
            return

        results = BinSearchService.search_by_rule_prefix(
            session=session,
            group_db_id=group.id,
            rule_prefix=search_keyword,
            limit=10
        )

        if not results:
            await update.message.reply_text(f"❌ 未找到以 `{search_keyword}` 开头的BIN信息", parse_mode="Markdown")
            reply_handler_manager.unregister(update.message.reply_to_message.message_id)
            return

        keyboard = []
        for bin_card in results:
            # 查询网站（按ID降序，最新的在前）
            sites = session.exec(
                select(BinSite)
                .where(BinSite.bin_card_id == bin_card.id)
                .order_by(BinSite.id.desc())
            ).all()

            # 构建网站名称显示
            if sites:
                site_names = [s.site_name for s in sites[:3]]  # 最多显示3个
                sites_text = ", ".join(site_names)
                if len(sites) > 3:
                    sites_text += "..."
            else:
                sites_text = "无网站"

            keyboard.append([
                InlineKeyboardButton(
                    f"💳 {bin_card.rule} - {sites_text}",
                    callback_data=f"bin_result_{bin_card.id}"
                )
            ])

        result_msg = await update.message.reply_text(
            f"🔍 找到 **{len(results)}** 条结果：",
            reply_markup=InlineKeyboardMarkup(keyboard),
            parse_mode="Markdown"
        )

        # 30秒后自动删除用户输入消息和结果消息
        asyncio.create_task(_delete_message_later(context.bot, chat_id, update.message.message_id, 300))
        asyncio.create_task(_delete_message_later(context.bot, chat_id, result_msg.message_id, 300))

    reply_handler_manager.unregister(update.message.reply_to_message.message_id)


async def handle_bin_site_search_input(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """处理网站名搜索"""
    search_keyword = update.message.text.strip()

    if not search_keyword:
        await update.message.reply_text("❌ 请输入网站名称")
        return

    chat_id = update.effective_chat.id

    with Session(engine) as session:
        group = session.exec(
            select(GroupConfig).where(GroupConfig.group_id == chat_id)
        ).first()

        if not group:
            await update.message.reply_text("❌ 群组未初始化")
            reply_handler_manager.unregister(update.message.reply_to_message.message_id)
            return

        results = BinSearchService.search_by_site_name(
            session=session,
            group_db_id=group.id,
            site_keyword=search_keyword,
            limit=10
        )

        if not results:
            await update.message.reply_text(f"❌ 未找到包含 `{search_keyword}` 的网站", parse_mode="Markdown")
            reply_handler_manager.unregister(update.message.reply_to_message.message_id)
            return

        keyboard = []
        for bin_card in results:
            # 查询网站（按ID降序，最新的在前）
            sites = session.exec(
                select(BinSite)
                .where(BinSite.bin_card_id == bin_card.id)
                .order_by(BinSite.id.desc())
            ).all()

            # 构建网站名称显示
            if sites:
                site_names = [s.site_name for s in sites[:3]]  # 最多显示3个
                sites_text = ", ".join(site_names)
                if len(sites) > 3:
                    sites_text += "..."
            else:
                sites_text = "无网站"

            keyboard.append([
                InlineKeyboardButton(
                    f"💳 {bin_card.rule} - {sites_text}",
                    callback_data=f"bin_result_{bin_card.id}"
                )
            ])

        result_msg = await update.message.reply_text(
            f"🔍 找到 **{len(results)}** 条结果：",
            reply_markup=InlineKeyboardMarkup(keyboard),
            parse_mode="Markdown"
        )

        # 30秒后自动删除用户输入消息和结果消息
        asyncio.create_task(_delete_message_later(context.bot, chat_id, update.message.message_id, 300))
        asyncio.create_task(_delete_message_later(context.bot, chat_id, result_msg.message_id, 300))

    reply_handler_manager.unregister(update.message.reply_to_message.message_id)


async def handle_bin_domain_search_input(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """处理域名搜索"""
    search_keyword = update.message.text.strip()

    if not search_keyword:
        await update.message.reply_text("❌ 请输入域名")
        return

    chat_id = update.effective_chat.id

    with Session(engine) as session:
        group = session.exec(
            select(GroupConfig).where(GroupConfig.group_id == chat_id)
        ).first()

        if not group:
            await update.message.reply_text("❌ 群组未初始化")
            reply_handler_manager.unregister(update.message.reply_to_message.message_id)
            return

        results = BinSearchService.search_by_domain(
            session=session,
            group_db_id=group.id,
            domain=search_keyword,
            limit=10
        )

        if not results:
            await update.message.reply_text(f"❌ 未找到域名 `{search_keyword}` 相关的BIN信息", parse_mode="Markdown")
            reply_handler_manager.unregister(update.message.reply_to_message.message_id)
            return

        keyboard = []
        for bin_card in results:
            # 查询网站（按ID降序，最新的在前）
            sites = session.exec(
                select(BinSite)
                .where(BinSite.bin_card_id == bin_card.id)
                .order_by(BinSite.id.desc())
            ).all()

            # 构建网站名称显示
            if sites:
                site_names = [s.site_name for s in sites[:3]]  # 最多显示3个
                sites_text = ", ".join(site_names)
                if len(sites) > 3:
                    sites_text += "..."
            else:
                sites_text = "无网站"

            keyboard.append([
                InlineKeyboardButton(
                    f"💳 {bin_card.rule} - {sites_text}",
                    callback_data=f"bin_result_{bin_card.id}"
                )
            ])

        result_msg = await update.message.reply_text(
            f"🔍 找到 **{len(results)}** 条结果：",
            reply_markup=InlineKeyboardMarkup(keyboard),
            parse_mode="Markdown"
        )

        # 30秒后自动删除用户输入消息和结果消息
        asyncio.create_task(_delete_message_later(context.bot, chat_id, update.message.message_id, 300))
        asyncio.create_task(_delete_message_later(context.bot, chat_id, result_msg.message_id, 300))

    reply_handler_manager.unregister(update.message.reply_to_message.message_id)


async def handle_bin_sender_search_input(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """处理发送者搜索"""
    search_keyword = update.message.text.strip()

    if not search_keyword:
        await update.message.reply_text("❌ 请输入用户名或用户ID")
        return

    chat_id = update.effective_chat.id

    with Session(engine) as session:
        group = session.exec(
            select(GroupConfig).where(GroupConfig.group_id == chat_id)
        ).first()

        if not group:
            await update.message.reply_text("❌ 群组未初始化")
            reply_handler_manager.unregister(update.message.reply_to_message.message_id)
            return

        results = BinSearchService.search_by_sender(
            session=session,
            group_db_id=group.id,
            sender_identifier=search_keyword,
            limit=10
        )

        if not results:
            await update.message.reply_text(f"❌ 未找到发送者 `{search_keyword}` 的BIN信息", parse_mode="Markdown")
            reply_handler_manager.unregister(update.message.reply_to_message.message_id)
            return

        keyboard = []
        for bin_card in results:
            # 查询网站（按ID降序，最新的在前）
            sites = session.exec(
                select(BinSite)
                .where(BinSite.bin_card_id == bin_card.id)
                .order_by(BinSite.id.desc())
            ).all()

            # 构建网站名称显示
            if sites:
                site_names = [s.site_name for s in sites[:3]]  # 最多显示3个
                sites_text = ", ".join(site_names)
                if len(sites) > 3:
                    sites_text += "..."
            else:
                sites_text = "无网站"

            keyboard.append([
                InlineKeyboardButton(
                    f"💳 {bin_card.rule} - {sites_text}",
                    callback_data=f"bin_result_{bin_card.id}"
                )
            ])

        result_msg = await update.message.reply_text(
            f"🔍 找到 **{len(results)}** 条结果：",
            reply_markup=InlineKeyboardMarkup(keyboard),
            parse_mode="Markdown"
        )

        # 30秒后自动删除用户输入消息和结果消息
        asyncio.create_task(_delete_message_later(context.bot, chat_id, update.message.message_id, 300))
        asyncio.create_task(_delete_message_later(context.bot, chat_id, result_msg.message_id, 300))

    reply_handler_manager.unregister(update.message.reply_to_message.message_id)


async def generate_card_callback(update: Update, context: ContextTypes.DEFAULT_TYPE, bin_id: int):
    """生成卡片回调（生成30张）"""
    query = update.callback_query
    await query.answer("🎲 正在生成30张卡片...")

    with Session(engine) as session:
        bin_card = session.get(BinCard, bin_id)
        if not bin_card:
            await query.answer("❌ BIN信息不存在", show_alert=True)
            return

        # 生成30张卡片
        cards = []
        for _ in range(30):
            generated_card = generate_card_from_rule(bin_card.rule)
            cards.append(f"`{generated_card}`")

        # 构建消息
        card_text = f"🎲 **生成的卡片** (30张)\n\n基于规则: `{bin_card.rule}`\n\n"
        card_text += "\n".join(cards)

        # 回复到详情消息
        card_msg = await context.bot.send_message(
            chat_id=query.message.chat_id,
            text=card_text,
            reply_to_message_id=query.message.message_id,
            parse_mode="Markdown"
        )

        # 30秒后自动删除生成的卡片消息
        asyncio.create_task(_delete_message_later(context.bot, query.message.chat_id, card_msg.message_id, 300))


async def handle_bin_browse_callback(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """处理浏览BIN的回调"""
    query = update.callback_query
    data = query.data

    # 解析回调数据: bin_browse_{order_by}_{order_dir}_{page}
    parts = data.split("_")
    if len(parts) < 5:
        await query.answer("❌ 无效的回调数据", show_alert=True)
        return

    order_by = parts[2]  # time, rule, sender
    order_dir = parts[3]  # desc, asc
    page = int(parts[4])

    chat_id = update.effective_chat.id

    with Session(engine) as session:
        group = session.exec(
            select(GroupConfig).where(GroupConfig.group_id == chat_id)
        ).first()

        if not group:
            await query.answer("❌ 群组未初始化", show_alert=True)
            return

        # 获取BIN列表
        results, total = BinSearchService.browse_all(
            session=session,
            group_db_id=group.id,
            order_by=order_by,
            order_dir=order_dir,
            page=page,
            page_size=10
        )

        if not results:
            await query.edit_message_text("❌ 没有找到任何BIN信息")
            return

        # 构建排序说明
        order_emoji = {"time": "🕒", "rule": "🔢", "sender": "👤"}
        order_name = {"time": "时间", "rule": "卡头", "sender": "发送者"}
        order_dir_name = {"desc": "降序", "asc": "升序"}
        order_dir_emoji = {"desc": "⬇️", "asc": "⬆️"}

        current_order = f"{order_emoji.get(order_by, '')} {order_name.get(order_by, '')} {order_dir_emoji.get(order_dir, '')} {order_dir_name.get(order_dir, '')}"

        # 构建结果按钮
        keyboard = []
        for bin_card in results:
            # 查询网站
            sites = session.exec(
                select(BinSite)
                .where(BinSite.bin_card_id == bin_card.id)
                .order_by(BinSite.id.desc())
            ).all()

            # 构建显示文本
            if sites:
                site_names = [s.site_name for s in sites[:2]]
                sites_text = ", ".join(site_names)
                if len(sites) > 2:
                    sites_text += "..."
            else:
                sites_text = "无网站"

            # 显示发送者（如果按发送者排序）
            sender_info = ""
            if order_by == "sender" and bin_card.sender_username:
                sender_info = f" - @{bin_card.sender_username}"

            # 在callback_data中包含返回信息
            callback_data = f"bin_result_{bin_card.id}_browse_{order_by}_{order_dir}_{page}"
            keyboard.append([
                InlineKeyboardButton(
                    f"💳 {bin_card.rule} | {sites_text}{sender_info}",
                    callback_data=callback_data
                )
            ])

        # 构建分页和排序按钮
        total_pages = (total + 9) // 10  # 向上取整
        nav_buttons = []

        # 切换排序方向按钮
        new_order_dir = "asc" if order_dir == "desc" else "desc"
        nav_buttons.append(
            InlineKeyboardButton(
                f"🔄 {order_dir_name.get(new_order_dir, '')}",
                callback_data=f"bin_browse_{order_by}_{new_order_dir}_1"
            )
        )

        if nav_buttons:
            keyboard.append(nav_buttons)

        # 分页按钮
        page_buttons = []
        if page > 1:
            page_buttons.append(
                InlineKeyboardButton("⬅️ 上一页", callback_data=f"bin_browse_{order_by}_{order_dir}_{page-1}")
            )
        if page < total_pages:
            page_buttons.append(
                InlineKeyboardButton("下一页 ➡️", callback_data=f"bin_browse_{order_by}_{order_dir}_{page+1}")
            )
        if page_buttons:
            keyboard.append(page_buttons)

        # 返回按钮
        keyboard.append([InlineKeyboardButton("🔙 返回", callback_data="bin_browse_back")])

        # 构建消息文本
        text = f"📚 **BIN信息浏览**\n\n"
        text += f"**排序**: {current_order}\n"
        text += f"**页码**: {page}/{total_pages}\n"
        text += f"**总数**: {total} 条\n\n"
        text += "点击下方按钮查看详情："

        await query.edit_message_text(
            text,
            reply_markup=InlineKeyboardMarkup(keyboard),
            parse_mode="Markdown"
        )


async def show_bin_detail(update: Update, context: ContextTypes.DEFAULT_TYPE, bin_id: int, source_context: dict = None):
    """
    显示BIN详细信息

    Args:
        update: Telegram更新对象
        context: 上下文
        bin_id: BIN卡片ID
        source_context: 来源上下文，包含返回信息
                       例如: {"source": "browse", "order_by": "time", "order_dir": "desc", "page": "1"}
    """
    query = update.callback_query

    with Session(engine) as session:
        bin_card = session.get(BinCard, bin_id)
        if not bin_card:
            await query.edit_message_text("❌ BIN信息不存在")
            return

        # 获取群组的Telegram ID
        group = session.get(GroupConfig, bin_card.group_id)
        if not group:
            await query.edit_message_text("❌ 群组信息不存在")
            return

        sites = session.exec(
            select(BinSite).where(BinSite.bin_card_id == bin_id)
        ).all()

        text = f"💳 **BIN信息详情**\n\n"
        text += f"**规则**: `{bin_card.rule}`\n"

        # 显示BIN信息（如果有）
        if bin_card.bin_scheme or bin_card.bin_type or bin_card.bin_brand:
            text += f"\n**BIN信息**:\n"
            if bin_card.bin_scheme and bin_card.bin_type and bin_card.bin_brand:
                text += f"  • 类型: {bin_card.bin_scheme} - {bin_card.bin_type} - {bin_card.bin_brand}\n"
            if bin_card.bin_bank and bin_card.bin_bank != 'Unknown':
                text += f"  • 发卡行: {bin_card.bin_bank}\n"
            if bin_card.bin_country and bin_card.bin_country != 'Unknown':
                country_flag = bin_card.bin_country_emoji if bin_card.bin_country_emoji else ''
                text += f"  • 国家: {country_flag} {bin_card.bin_country}\n"

        if sites:
            text += f"\n**适用网站** ({len(sites)}):\n"
            for site in sites:
                text += f"  • {site.site_name} (`{site.site_domain}`)\n"

        if bin_card.ip_requirement:
            text += f"\n**IP要求**: {bin_card.ip_requirement}\n"

        if bin_card.credits:
            text += f"**贡献者**: {bin_card.credits}\n"

        if bin_card.notes:
            text += f"\n**备注**: {bin_card.notes}\n"

        # 构建消息链接 (私密群组需要使用 -100 前缀去掉后的ID)
        # Telegram群组ID格式: -1001234567890 -> 链接使用: 1234567890
        tg_group_id = str(group.group_id).replace('-100', '')
        message_link = f"https://t.me/c/{tg_group_id}/{bin_card.topic_id}/{bin_card.message_id}"
        text += f"\n**[来源消息]({message_link})**\n"

        if bin_card.sender_username:
            text += f"**发送者**: @{bin_card.sender_username}\n"

        # 转换为中国时区（UTC+8）
        from datetime import timedelta
        cst_time = bin_card.created_at + timedelta(hours=8)
        text += f"\n**记录时间**: {cst_time.strftime('%Y-%m-%d %H:%M')}\n"

        # 根据来源构建返回按钮
        keyboard = [
            [InlineKeyboardButton("🎲 生成卡片", callback_data=f"bin_generate_{bin_card.id}")]
        ]

        if source_context and source_context.get("source") == "browse":
            # 从浏览进入，返回到浏览页面
            order_by = source_context.get("order_by")
            order_dir = source_context.get("order_dir")
            page = source_context.get("page")
            keyboard.append([
                InlineKeyboardButton("🔙 返回浏览", callback_data=f"bin_browse_{order_by}_{order_dir}_{page}")
            ])
        else:
            # 从搜索进入，返回到搜索菜单
            keyboard.append([
                InlineKeyboardButton("🔙 返回搜索", callback_data="bin_search_back")
            ])

        await query.edit_message_text(
            text,
            reply_markup=InlineKeyboardMarkup(keyboard),
            parse_mode="Markdown"
        )

        # 详情消息300秒后自动删除
        asyncio.create_task(_delete_message_later(context.bot, query.message.chat_id, query.message.message_id, 300))
