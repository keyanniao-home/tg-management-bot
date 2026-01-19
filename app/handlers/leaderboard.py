"""
Main leaderboard command handler.

Provides the /kobe_leaderboard command and callback handlers for
navigation, pagination, and leaderboard display.
"""

from sqlmodel import Session, select
from telegram import Update, InlineKeyboardButton, InlineKeyboardMarkup
from telegram.ext import ContextTypes

from app.database.connection import engine
from app.handlers.leaderboards import registry
from app.models import GroupConfig
from app.utils.auto_delete import auto_delete_message
from app.utils.rate_limiter import rate_limit_callback


@auto_delete_message(delay=30, custom_delays={'leaderboard': 120})
async def leaderboard_command(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """
    /kobe_leaderboard or /kobe_榜单
    Show list of enabled leaderboards with inline buttons.
    """
    with Session(engine) as session:
        statement = select(GroupConfig).where(
            GroupConfig.group_id == update.effective_chat.id
        )
        group = session.exec(statement).first()

        if not group:
            return await update.message.reply_text("群组未初始化")

        # Get enabled leaderboards
        enabled_leaderboards = registry.get_enabled(group.config)

        if not enabled_leaderboards:
            return None

        # Build leaderboard selection buttons
        keyboard = []
        for lb in enabled_leaderboards:
            keyboard.append([
                InlineKeyboardButton(
                    f"{lb.emoji} {lb.display_name}",
                    callback_data=f"lb_select:{lb.leaderboard_id}:1:7"  # default 7 days
                )
            ])

        reply_markup = InlineKeyboardMarkup(keyboard)

        text = "📊 *榜单列表*\n\n请选择要查看的榜单："
        return await update.message.reply_text(
            text,
            reply_markup=reply_markup,
            parse_mode="Markdown"
        )


@rate_limit_callback(global_interval=0.5, user_interval=0.3)
async def leaderboard_callback(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """
    Handle leaderboard pagination and navigation.

    Callback formats:
    - lb_select:<lb_id>:<page>:<days> - Select leaderboard from list
    - lb_view:<lb_id>:<page>:<days> - View/paginate leaderboard
    - lb_back - Return to leaderboard list
    """
    query = update.callback_query
    await query.answer()

    parts = query.data.split(":")
    action = parts[0]

    try:
        if action == "lb_select":
            # Initial selection from list
            lb_id = parts[1]
            page = int(parts[2])
            days = int(parts[3])
            await _show_leaderboard_view(query, lb_id, page, days, 0)

        elif action == "lb_view":
            # Navigate within leaderboard (pagination, time range change)
            lb_id = parts[1]
            page = int(parts[2])
            days = int(parts[3])
            await _show_leaderboard_view(query, lb_id, page, days, 0)

        elif action == "lb_back":
            # Return to leaderboard list
            await _show_leaderboard_list(query)

        else:
            await query.edit_message_text("未知的操作")

    except (IndexError, ValueError) as e:
        await query.edit_message_text("数据格式错误")
    except Exception as e:
        # Silently ignore "message not modified" errors
        error_msg = str(e)
        if "message is not modified" not in error_msg.lower():
            await query.answer(f"操作失败: {error_msg}", show_alert=True)


async def _show_leaderboard_view(query, lb_id: str, page: int, days: int, pattern_idx: int = 0):
    """Display specific leaderboard with data."""
    with Session(engine) as session:
        statement = select(GroupConfig).where(
            GroupConfig.group_id == query.message.chat_id
        )
        group = session.exec(statement).first()

        if not group:
            await query.edit_message_text("群组未初始化")
            return

        leaderboard = registry.get(lb_id)
        if not leaderboard or not leaderboard.is_enabled(group.config):
            await query.edit_message_text("榜单未启用或不存在")
            return

        # Query leaderboard data
        page_size = 10
        offset = (page - 1) * page_size
        entries, total_count = leaderboard.query_data(
            session, group.id, days, page_size, offset
        )

        # Handle empty results
        if not entries:
            title = f"{leaderboard.emoji} {leaderboard.display_name}"

            # Different message for night shift vs other leaderboards
            from app.handlers.leaderboards.night_shift import NightShiftLeaderboard
            if isinstance(leaderboard, NightShiftLeaderboard):
                text = f"{title}\n\n最近一次值班时段暂无数据"
            else:
                text = f"{title}\n\n近{days}天内暂无数据"

            # Still show navigation buttons
            keyboard = _build_leaderboard_buttons(
                leaderboard, lb_id, page, days, 0, group.config
            )
            reply_markup = InlineKeyboardMarkup(keyboard) if keyboard else None

            await query.edit_message_text(text, reply_markup=reply_markup)
            return

        # Format display
        display_mode = group.config.get('leaderboard_display_mode',
                                        group.config.get('stats_display_mode', 'mention'))
        total_pages = (total_count + page_size - 1) // page_size
        page = min(max(page, 1), total_pages)  # Bounds check

        # Build title
        from app.handlers.leaderboards.night_shift import NightShiftLeaderboard
        title = f"{leaderboard.emoji} {leaderboard.display_name}"

        # Different title format for night shift
        if isinstance(leaderboard, NightShiftLeaderboard):
            text = f"{title}（第{page}/{total_pages}页，共{total_count}人）\n\n"
        else:
            text = f"{title}（第{page}/{total_pages}页，共{total_count}人，近{days}天）\n\n"

        # Format entries
        for i, entry in enumerate(entries, start=offset + 1):
            text += leaderboard.format_entry(i, entry, display_mode)
            text += "\n"

        # Build button layout
        keyboard = _build_leaderboard_buttons(
            leaderboard, lb_id, page, days, total_pages, group.config
        )

        reply_markup = InlineKeyboardMarkup(keyboard)
        await query.edit_message_text(
            text,
            reply_markup=reply_markup,
            parse_mode="MarkdownV2"
        )


def _build_leaderboard_buttons(leaderboard, lb_id: str, page: int, days: int,
                               total_pages: int, group_config: dict) -> list:
    """Build inline keyboard buttons for leaderboard navigation."""
    from app.handlers.leaderboards.night_shift import NightShiftLeaderboard

    keyboard = []

    # Row 1: Return to list button
    keyboard.append([
        InlineKeyboardButton("« 返回榜单列表", callback_data="lb_back")
    ])

    # Row 2: Time range selector (only for non-night-shift leaderboards)
    if not isinstance(leaderboard, NightShiftLeaderboard):
        time_buttons = []
        for d in [1, 7, 30]:
            label = f"{'✓ ' if d == days else ''}{d}天"
            callback_data = f"lb_view:{lb_id}:1:{d}"
            time_buttons.append(
                InlineKeyboardButton(label, callback_data=callback_data)
            )
        keyboard.append(time_buttons)

    # Row 3: Pagination (only if multiple pages)
    if total_pages > 1:
        page_buttons = []
        if page > 1:
            callback_data = f"lb_view:{lb_id}:{page - 1}:{days}"
            page_buttons.append(
                InlineKeyboardButton("⬅️ 上一页", callback_data=callback_data)
            )
        if page < total_pages:
            callback_data = f"lb_view:{lb_id}:{page + 1}:{days}"
            page_buttons.append(
                InlineKeyboardButton("➡️ 下一页", callback_data=callback_data)
            )
        if page_buttons:
            keyboard.append(page_buttons)

    return keyboard


async def _show_leaderboard_list(query):
    """Return to leaderboard list (edit message)."""
    with Session(engine) as session:
        statement = select(GroupConfig).where(
            GroupConfig.group_id == query.message.chat_id
        )
        group = session.exec(statement).first()

        if not group:
            await query.edit_message_text("群组未初始化")
            return

        enabled_leaderboards = registry.get_enabled(group.config)

        if not enabled_leaderboards:
            await query.edit_message_text(
                "当前没有启用的榜单\n\n"
                "管理员可使用以下命令启用榜单：\n"
                "/kobe_config leaderboards.night_shift.enabled true\n"
                "/kobe_config leaderboards.keyword.enabled true"
            )
            return

        keyboard = []
        for lb in enabled_leaderboards:
            keyboard.append([
                InlineKeyboardButton(
                    f"{lb.emoji} {lb.display_name}",
                    callback_data=f"lb_select:{lb.leaderboard_id}:1:7"
                )
            ])

        reply_markup = InlineKeyboardMarkup(keyboard)
        text = "📊 *榜单列表*\n\n请选择要查看的榜单："
        await query.edit_message_text(
            text,
            reply_markup=reply_markup,
            parse_mode="Markdown"
        )
