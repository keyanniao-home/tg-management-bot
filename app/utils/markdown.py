"""
Markdown工具函数
"""


def escape_markdown_v2(text: str) -> str:
    """
    转义MarkdownV2特殊字符

    需要转义的字符: _*[]()~`>#+-=|{}.!\\

    Args:
        text: 需要转义的文本

    Returns:
        转义后的文本
    """
    if not text:
        return text
    escape_chars = r'_*[]()~`>#+-=|{}.!\\'
    return ''.join('\\' + char if char in escape_chars else char for char in text)
