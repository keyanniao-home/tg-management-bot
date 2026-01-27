from dataclasses import dataclass
from typing import Optional
import httpx
from loguru import logger
from app.config.settings import settings


@dataclass
class BinInfo:
    """BIN信息数据类"""
    scheme: str
    type: str
    brand: str
    country_name: str
    country_emoji: str
    bank_name: str


# 全局缓存字典，避免重复查询
_bin_info_cache: dict[str, Optional[BinInfo]] = {}


async def get_bin_info(card_bin: str) -> Optional[BinInfo]:
    """
    异步查询BIN信息（带内存缓存）

    Args:
        card_bin: 卡号前缀（BIN），通常是前6-8位数字

    Returns:
        BinInfo对象，如果查询失败返回None
    """
    try:
        # 只取前6-8位数字
        bin_digits = ''.join(c for c in card_bin if c.isdigit())[:8]
        if not bin_digits or len(bin_digits) < 6:
            logger.warning(f"无效的BIN: {card_bin}")
            return None

        # 检查缓存
        if bin_digits in _bin_info_cache:
            logger.debug(f"使用缓存的BIN信息: {bin_digits}")
            return _bin_info_cache[bin_digits]

        url = f'{settings.bin_info_url}/{bin_digits}'

        # 使用异步HTTP客户端
        async with httpx.AsyncClient() as client:
            response = await client.get(url, timeout=5.0)
            response.raise_for_status()
            data = response.json()

        # 检查是否有有效的number字段
        if data.get('number') is None:
            logger.debug(f"BIN信息API未返回有效数据: {bin_digits}")
            _bin_info_cache[bin_digits] = None
            return None

        # 提取信息，使用默认值避免None
        scheme = data.get('scheme') or 'Unknown'
        card_type = data.get('type') or 'Unknown'
        brand = data.get('brand') or 'Unknown'
        country_name = data.get('country', {}).get('name') or 'Unknown'
        country_emoji = data.get('country', {}).get('emoji') or ''
        bank_name = data.get('bank', {}).get('name') or 'Unknown'

        bin_info = BinInfo(
            scheme=scheme,
            type=card_type,
            brand=brand,
            country_name=country_name,
            country_emoji=country_emoji,
            bank_name=bank_name
        )

        # 缓存结果
        _bin_info_cache[bin_digits] = bin_info
        logger.debug(f"已缓存BIN信息: {bin_digits}")

        return bin_info

    except httpx.TimeoutException:
        logger.warning(f"BIN信息查询超时: {card_bin}")
        return None
    except httpx.HTTPError as e:
        logger.warning(f"BIN信息查询失败: {card_bin}, error={e}")
        return None
    except Exception as e:
        logger.exception(f"BIN信息处理异常: {card_bin}, error={e}")
        return None


def clear_bin_info_cache():
    """清空BIN信息缓存"""
    global _bin_info_cache
    _bin_info_cache.clear()
    logger.info("BIN信息缓存已清空")
