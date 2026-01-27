from typing import List, Optional
from loguru import logger
from sqlmodel import Session, select
from app.models.bin_card import BinCard
from app.models.bin_site import BinSite
from app.services.bin.models import BinCardInfo
from app.services.bin.parser import BinParser
from app.services.bin.info_service import get_bin_info


class BinStorage:
    """BIN数据存储服务"""

    @staticmethod
    async def save_bin_cards(
        session: Session,
        group_db_id: int,
        topic_id: int,
        message_id: int,
        sender_user_id: Optional[int],
        sender_username: Optional[str],
        sender_chat_id: Optional[int],
        original_text: str,
        cards: List[BinCardInfo]
    ) -> tuple[int, List[str]]:
        """
        保存BIN卡信息（异步）

        Returns:
            (实际保存的卡片数量, 重复的规则列表)
        """
        saved_count = 0
        duplicates = []

        for card_info in cards:
            try:
                # 检查是否有有效的网站信息
                valid_sites = [
                    site for site in card_info.sites
                    if site.name and site.name.strip() and site.domain and site.domain.strip()
                ]

                if not valid_sites:
                    logger.debug(f"跳过无有效网站信息的BIN卡: rule={card_info.rule}")
                    continue

                # 检查每个域名是否与该rule已存在
                should_skip = False
                for site_info in valid_sites:
                    normalized_domain = BinParser.normalize_domain(site_info.domain)
                    if not normalized_domain:
                        continue

                    # 检查 rule + domain 组合是否已存在
                    existing = session.exec(
                        select(BinCard)
                        .join(BinSite, BinCard.id == BinSite.bin_card_id)
                        .where(
                            BinCard.group_id == group_db_id,
                            BinCard.rule == card_info.rule,
                            BinSite.site_domain == normalized_domain
                        )
                    ).first()

                    if existing:
                        logger.debug(f"BIN+域名组合已存在，跳过: rule={card_info.rule}, domain={normalized_domain}")
                        duplicates.append(f"{card_info.rule} ({normalized_domain})")
                        should_skip = True
                        break

                if should_skip:
                    continue

                # 提取规则前缀
                rule_prefix = BinParser.extract_rule_prefix(card_info.rule)

                # 异步查询BIN信息
                bin_info = None
                try:
                    bin_info = await get_bin_info(rule_prefix)
                    if bin_info:
                        logger.debug(f"成功查询BIN信息: {rule_prefix} -> {bin_info.scheme} {bin_info.brand}")
                except Exception as e:
                    logger.warning(f"查询BIN信息失败，继续保存: {e}")

                # 创建BinCard记录
                bin_card = BinCard(
                    group_id=group_db_id,
                    topic_id=topic_id,
                    message_id=message_id,
                    sender_user_id=sender_user_id,
                    sender_username=sender_username,
                    sender_chat_id=sender_chat_id,
                    rule=card_info.rule,
                    rule_prefix=rule_prefix,
                    ip_requirement=card_info.ip,
                    credits=card_info.credits,
                    notes=card_info.notes,
                    # BIN信息（如果查询成功）
                    bin_scheme=bin_info.scheme if bin_info else None,
                    bin_type=bin_info.type if bin_info else None,
                    bin_brand=bin_info.brand if bin_info else None,
                    bin_country=bin_info.country_name if bin_info else None,
                    bin_country_emoji=bin_info.country_emoji if bin_info else None,
                    bin_bank=bin_info.bank_name if bin_info else None,
                    original_text=original_text
                )
                session.add(bin_card)
                session.commit()
                session.refresh(bin_card)

                # 创建关联的网站记录（使用过滤后的valid_sites）
                for site_info in valid_sites:
                    normalized_domain = BinParser.normalize_domain(site_info.domain)

                    if not normalized_domain:
                        logger.warning(f"无效域名，跳过: {site_info.domain}")
                        continue

                    bin_site = BinSite(
                        bin_card_id=bin_card.id,
                        site_name=site_info.name,
                        site_domain=normalized_domain
                    )
                    session.add(bin_site)

                session.commit()
                saved_count += 1

            except Exception as e:
                logger.exception(f"保存BIN卡失败: rule={card_info.rule}, error={e}")
                session.rollback()
                continue

        return saved_count, duplicates
