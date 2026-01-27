from app.models.group import GroupConfig, GroupAdmin, BanRecord
from app.models.member import GroupMember
from app.models.message import Message
from app.models.user_profile import UserProfile, UserChannel, ChannelMessage
from app.models.channel_binding import ChannelBinding
from app.models.points import UserPoints, CheckIn, PointsTransaction
from app.models.summary import MessageSummary
from app.models.digest_config import DigestConfig
from app.models.scammer_detection import ScammerDetectionRecord
from app.models.crawl_task import CrawlTask, CrawlTaskStatus
from app.models.db_version import DBVersion

# 新增资源管理模型 - 从各自的文件导入
from app.models.category import Category
from app.models.tag import Tag
from app.models.resource import Resource, ResourceTag, ResourceEdit
from app.models.dm_relay import DMRelay, DMReadReceipt
from app.models.bin_config import BinConfig
from app.models.bin_card import BinCard
from app.models.bin_site import BinSite

__all__ = [
    "GroupConfig",
    "GroupAdmin",
    "BanRecord",
    "GroupMember",
    "Message",
    "ChannelBinding",
    "UserProfile",
    "UserChannel",
    "ChannelMessage",
    "CrawlTask",
    "CrawlTaskStatus",
    "ScammerDetectionRecord",
    "MessageSummary",
    "UserPoints",
    "CheckIn",
    "PointsTransaction",
    "DBVersion",
    # 新增模型
    "Category",
    "Tag",
    "Resource",
    "ResourceTag",
    "ResourceEdit",
    "DMRelay",
    "DMReadReceipt",
    "DigestConfig",
    # BIN管理模型
    "BinConfig",
    "BinCard",
    "BinSite",
]

