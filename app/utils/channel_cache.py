"""频道权限缓存模块"""
from collections import OrderedDict
from datetime import datetime, timedelta, UTC
from typing import Optional


class ChannelPermissionCache:
    """
    频道权限缓存类
    缓存频道发言权限验证结果，减少数据库查询
    - 缓存期1小时
    - 用户退出时自动清除对应缓存
    """

    def __init__(self, capacity: int = 500, ttl_hours: int = 1):
        """
        初始化缓存

        Args:
            capacity: 最大缓存容量
            ttl_hours: 缓存过期时间（小时）
        """
        self.cache = OrderedDict()
        self.capacity = capacity
        self.ttl = timedelta(hours=ttl_hours)

    def _make_key(self, channel_id: int, group_id: int) -> str:
        """生成缓存key"""
        return f"{channel_id}:{group_id}"

    def get(self, channel_id: int, group_id: int) -> Optional[bool]:
        """
        获取缓存的权限验证结果

        Args:
            channel_id: 频道ID
            group_id: 群组ID

        Returns:
            bool: True表示允许发言，False表示不允许，None表示缓存未命中或已过期
        """
        key = self._make_key(channel_id, group_id)

        if key not in self.cache:
            return None

        # 检查是否过期
        result, timestamp = self.cache[key]
        if datetime.now(UTC) - timestamp > self.ttl:
            # 过期，删除缓存
            del self.cache[key]
            return None

        # 移到最后（标记为最近使用）
        self.cache.move_to_end(key)
        return result

    def put(self, channel_id: int, group_id: int, allowed: bool):
        """
        设置缓存

        Args:
            channel_id: 频道ID
            group_id: 群组ID
            allowed: 是否允许发言
        """
        key = self._make_key(channel_id, group_id)

        # 存储结果和时间戳
        self.cache[key] = (allowed, datetime.now(UTC))

        if key in self.cache:
            self.cache.move_to_end(key)

        # 超出容量时移除最旧的
        if len(self.cache) > self.capacity:
            self.cache.popitem(last=False)

    def invalidate_user(self, user_id: int, group_id: int):
        """
        清除指定用户在指定群组的所有频道缓存
        当用户退出群组时调用

        Args:
            user_id: 用户ID
            group_id: 群组ID
        """
        # 需要删除所有该用户绑定的频道缓存
        # 由于我们不知道用户绑定了哪些频道，需要遍历所有包含该群组的缓存
        keys_to_delete = []
        for key in self.cache.keys():
            # key格式是 "channel_id:group_id"
            _, cached_group_id = key.split(":")
            if int(cached_group_id) == group_id:
                keys_to_delete.append(key)

        for key in keys_to_delete:
            del self.cache[key]

    def invalidate_channel(self, channel_id: int, group_id: int):
        """
        清除指定频道在指定群组的缓存

        Args:
            channel_id: 频道ID
            group_id: 群组ID
        """
        key = self._make_key(channel_id, group_id)
        if key in self.cache:
            del self.cache[key]

    def clear(self):
        """清空所有缓存"""
        self.cache.clear()

    def cleanup_expired(self):
        """清理所有过期的缓存项"""
        current_time = datetime.now(UTC)
        keys_to_delete = []

        for key, (_, timestamp) in self.cache.items():
            if current_time - timestamp > self.ttl:
                keys_to_delete.append(key)

        for key in keys_to_delete:
            del self.cache[key]


class GroupConfigCache:
    """
    群组配置缓存类
    缓存 GroupConfig 对象，减少频繁的数据库查询
    - 缓存期10分钟
    - 容量1000个群组
    """

    def __init__(self, capacity: int = 1000, ttl_minutes: int = 10):
        """
        初始化缓存

        Args:
            capacity: 最大缓存容量
            ttl_minutes: 缓存过期时间（分钟）
        """
        self.cache = OrderedDict()
        self.capacity = capacity
        self.ttl = timedelta(minutes=ttl_minutes)

    def get(self, group_telegram_id: int):
        """
        获取缓存的群组配置

        Args:
            group_telegram_id: Telegram群组ID

        Returns:
            GroupConfig对象，或None（缓存未命中或已过期）
        """
        if group_telegram_id not in self.cache:
            return None

        # 检查是否过期
        group_config, timestamp = self.cache[group_telegram_id]
        if datetime.now(UTC) - timestamp > self.ttl:
            # 过期，删除缓存
            del self.cache[group_telegram_id]
            return None

        # 移到最后（标记为最近使用）
        self.cache.move_to_end(group_telegram_id)
        return group_config

    def put(self, group_telegram_id: int, group_config):
        """
        设置缓存

        Args:
            group_telegram_id: Telegram群组ID
            group_config: GroupConfig对象
        """
        # 存储配置和时间戳
        self.cache[group_telegram_id] = (group_config, datetime.now(UTC))

        if group_telegram_id in self.cache:
            self.cache.move_to_end(group_telegram_id)

        # 超出容量时移除最旧的
        if len(self.cache) > self.capacity:
            self.cache.popitem(last=False)

    def invalidate(self, group_telegram_id: int):
        """
        清除指定群组的缓存

        Args:
            group_telegram_id: Telegram群组ID
        """
        if group_telegram_id in self.cache:
            del self.cache[group_telegram_id]

    def clear(self):
        """清空所有缓存"""
        self.cache.clear()


# 全局缓存实例
channel_permission_cache = ChannelPermissionCache(capacity=500, ttl_hours=1)
group_config_cache = GroupConfigCache(capacity=1000, ttl_minutes=10)
