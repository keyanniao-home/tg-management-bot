from typing import Optional
from sqlmodel import SQLModel, Field, Index, Relationship


class BinSite(SQLModel, table=True):
    """BIN对应的网站信息（多对多关系）"""
    __tablename__ = "bin_sites"

    id: Optional[int] = Field(default=None, primary_key=True)
    bin_card_id: int = Field(foreign_key="bin_cards.id", index=True)

    site_name: str = Field(max_length=100, index=True)
    site_domain: str = Field(max_length=200, index=True)  # 标准化后的域名

    # Relationship
    bin_card: Optional["BinCard"] = Relationship(back_populates="sites")

    __table_args__ = (
        Index("idx_bin_site_card_domain", "bin_card_id", "site_domain"),
    )
