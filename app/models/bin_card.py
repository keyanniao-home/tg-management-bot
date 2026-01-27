from datetime import datetime
from typing import Optional, List
from sqlmodel import SQLModel, Field, Column, BigInteger, TEXT, Index, Relationship


class BinCard(SQLModel, table=True):
    """BIN卡信息表"""
    __tablename__ = "bin_cards"

    id: Optional[int] = Field(default=None, primary_key=True)

    # group_id存储数据库内部ID
    group_id: int = Field(foreign_key="group_configs.id", index=True)
    topic_id: int = Field(sa_column=Column(BigInteger, nullable=False, index=True))

    # 原始消息信息
    message_id: int = Field(sa_column=Column(BigInteger, nullable=False))
    sender_user_id: Optional[int] = Field(sa_column=Column(BigInteger, nullable=True, index=True))
    sender_username: Optional[str] = Field(default=None, max_length=100, index=True)
    sender_chat_id: Optional[int] = Field(sa_column=Column(BigInteger, nullable=True))

    # BIN规则（如：37936303|xx|xx|xxxx）
    rule: str = Field(max_length=50, index=True)
    rule_prefix: str = Field(max_length=8, index=True, description="前8位数字用于快速搜索")

    # IP要求
    ip_requirement: Optional[str] = Field(default=None, max_length=100)

    # 贡献者（YAML中的credits字段）
    credits: Optional[str] = Field(default=None, max_length=100)

    # 备注
    notes: Optional[str] = Field(default=None, sa_column=Column(TEXT))

    # BIN信息（从第三方API查询）
    bin_scheme: Optional[str] = Field(default=None, max_length=50, description="卡组织（Visa/Mastercard等）")
    bin_type: Optional[str] = Field(default=None, max_length=50, description="卡类型（credit/debit等）")
    bin_brand: Optional[str] = Field(default=None, max_length=100, description="卡品牌")
    bin_country: Optional[str] = Field(default=None, max_length=100, description="发卡国家")
    bin_country_emoji: Optional[str] = Field(default=None, max_length=10, description="国家旗帜emoji")
    bin_bank: Optional[str] = Field(default=None, max_length=200, description="发卡银行")

    # 原始消息文本（用于审计）
    original_text: str = Field(sa_column=Column(TEXT))

    created_at: datetime = Field(default_factory=datetime.utcnow)

    # Relationship - 关联的网站
    sites: List["BinSite"] = Relationship(back_populates="bin_card", cascade_delete=True)

    __table_args__ = (
        Index("idx_bin_card_group_rule", "group_id", "rule"),
        Index("idx_bin_card_group_prefix", "group_id", "rule_prefix"),
    )
