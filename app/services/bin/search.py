from typing import List, Tuple, Literal
from sqlmodel import Session, select, desc, asc, or_, func
from app.models.bin_card import BinCard
from app.models.bin_site import BinSite


class BinSearchService:
    """BIN搜索服务"""

    @staticmethod
    def browse_all(
        session: Session,
        group_db_id: int,
        order_by: Literal["time", "rule", "sender"] = "time",
        order_dir: Literal["desc", "asc"] = "desc",
        page: int = 1,
        page_size: int = 10
    ) -> Tuple[List[BinCard], int]:
        """
        浏览所有BIN，支持排序和分页

        Args:
            session: 数据库会话
            group_db_id: 群组数据库ID
            order_by: 排序字段 (time=时间, rule=卡头, sender=发送者)
            order_dir: 排序方向 (desc=降序, asc=升序)
            page: 页码，从1开始
            page_size: 每页数量

        Returns:
            (BinCard列表, 总数量)
        """
        # 构建基础查询
        base_query = select(BinCard).where(BinCard.group_id == group_db_id)

        # 添加排序
        if order_by == "time":
            order_column = BinCard.created_at
        elif order_by == "rule":
            order_column = BinCard.rule
        elif order_by == "sender":
            order_column = BinCard.sender_username
        else:
            order_column = BinCard.created_at

        if order_dir == "desc":
            statement = base_query.order_by(desc(order_column))
        else:
            statement = base_query.order_by(asc(order_column))

        # 添加分页
        offset = (page - 1) * page_size
        statement = statement.offset(offset).limit(page_size)

        # 执行查询
        results = list(session.exec(statement).all())

        # 获取总数
        count_statement = select(func.count()).select_from(BinCard).where(BinCard.group_id == group_db_id)
        total = session.exec(count_statement).one()

        return results, total

    @staticmethod
    def search_by_rule_prefix(
        session: Session,
        group_db_id: int,
        rule_prefix: str,
        limit: int = 10
    ) -> List[BinCard]:
        """按rule前缀搜索（匹配完整规则的开头）"""
        statement = (
            select(BinCard)
            .where(
                BinCard.group_id == group_db_id,
                BinCard.rule.like(f"{rule_prefix}%")
            )
            .order_by(desc(BinCard.created_at))
            .limit(limit)
        )
        return list(session.exec(statement).all())

    @staticmethod
    def search_by_site_name(
        session: Session,
        group_db_id: int,
        site_keyword: str,
        limit: int = 10
    ) -> List[BinCard]:
        """按网站名模糊搜索"""
        statement = (
            select(BinCard)
            .join(BinSite, BinCard.id == BinSite.bin_card_id)
            .where(
                BinCard.group_id == group_db_id,
                BinSite.site_name.ilike(f"%{site_keyword}%")
            )
            .distinct()
            .order_by(desc(BinCard.created_at))
            .limit(limit)
        )
        return list(session.exec(statement).all())

    @staticmethod
    def search_by_domain(
        session: Session,
        group_db_id: int,
        domain: str,
        limit: int = 10
    ) -> List[BinCard]:
        """按域名精确搜索"""
        from app.services.bin.parser import BinParser
        normalized_domain = BinParser.normalize_domain(domain)

        statement = (
            select(BinCard)
            .join(BinSite, BinCard.id == BinSite.bin_card_id)
            .where(
                BinCard.group_id == group_db_id,
                BinSite.site_domain == normalized_domain
            )
            .distinct()
            .order_by(desc(BinCard.created_at))
            .limit(limit)
        )
        return list(session.exec(statement).all())

    @staticmethod
    def search_by_sender(
        session: Session,
        group_db_id: int,
        sender_identifier: str,
        limit: int = 10
    ) -> List[BinCard]:
        """按发送者搜索（支持用户名或ID）"""
        if sender_identifier.isdigit():
            # 按用户ID搜索
            statement = (
                select(BinCard)
                .where(
                    BinCard.group_id == group_db_id,
                    BinCard.sender_user_id == int(sender_identifier)
                )
                .order_by(desc(BinCard.created_at))
                .limit(limit)
            )
        else:
            # 按用户名搜索（移除@符号）
            username = sender_identifier.lstrip("@")
            statement = (
                select(BinCard)
                .where(
                    BinCard.group_id == group_db_id,
                    BinCard.sender_username.ilike(f"%{username}%")
                )
                .order_by(desc(BinCard.created_at))
                .limit(limit)
            )

        return list(session.exec(statement).all())
