from pydantic import BaseModel, Field
from typing import List, Optional


class BinSiteInfo(BaseModel):
    """单个网站信息"""
    name: str
    domain: str


class BinCardInfo(BaseModel):
    """单个BIN卡信息"""
    rule: str
    sites: List[BinSiteInfo]
    ip: Optional[str] = None
    credits: Optional[str] = None
    notes: Optional[str] = None


class BinParseResult(BaseModel):
    """AI解析结果"""
    cards: List[BinCardInfo] = Field(default_factory=list)
    error: Optional[str] = None
