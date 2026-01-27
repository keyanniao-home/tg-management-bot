from typing import Optional
from loguru import logger
import yaml
import re
from app.services.ai.service import ai_service
from app.services.bin.models import BinParseResult, BinCardInfo, BinSiteInfo


# 默认AI Prompt（JSON格式，非YAML）
DEFAULT_BIN_PROMPT = """你是一个 卡片生成规则 解析助手，负责从不定格式的用户消息中提取卡片生成规则。

## 任务
1. 判断用户消息是否包含 卡片生成规则
2. 提取所有 卡片生成规则 及其配置
3. 将网站名称转换为域名（可少量纠错）
4. 以 YAML 格式输出结构化数据

## 核心规则

### BIN 处理
- **根据卡组织补齐到标准位数**
- `x` 表示随机数字
- 如果用户提供的BIN不足标准位数，需要补充`x`到标准位数

### 卡组织标准位数和CVV
| 卡头首位 | 卡组织 | 标准卡号位数 | CVV |
|---------|--------|------------|-----|
| 3 | AMEX | 15位 | xxxx |
| 4 | Visa | 16位 | xxx |
| 5 | Mastercard | 16位 | xxx |
| 6 | Discover | 16位 | xxx |
| 其他 | 未知 | 16位 | xxx |

**补齐规则示例**：
- `453201` (6位Visa) → `453201xxxxxxxxxx` (补齐到16位)
- `379363` (6位AMEX) → `379363xxxxxxxxx` (补齐到15位)
- `531247` (6位Mastercard) → `531247xxxxxxxxxx` (补齐到16位)
- `4532018888888888` (已经16位) → 保持不变
- `37936303` (8位AMEX) → `37936303xxxxxxx` (补齐到15位)

### 日期
- 未指定 → `xx`
- 指定值 → 使用具体值

### 网站名称转域名
将常见网站名称转换为对应域名：

| 名称 | 域名 |
|------|------|
| Netflix | netflix.com |
| Spotify | spotify.com |
| ChatGPT / OpenAI | openai.com |
| Claude / Anthropic | anthropic.com |
| Disney+ / Disney Plus | disneyplus.com |
| Hulu | hulu.com |
| Amazon / Amazon Prime | amazon.com |
| HBO / HBO Max | max.com |
| YouTube / YouTube Premium | youtube.com |
| Apple / Apple Music | apple.com |
| Midjourney | midjourney.com |
| GitHub Copilot | github.com |
| ... | (根据常识推断) |

如果已经是域名则保留原样。

## 输出格式

```yaml
cards:
  - rule: "BIN|月|年|CVV"
    sites:
      - name: "网站名称"
        domain: "域名"
    ip: "IP要求或null"
    credits: "来源或null"
    notes: "备注或null"
```

## 示例

### 示例 1：AMEX卡（8位BIN补齐到15位）
输入：
```
Site : Landingsite.ai
Bin : 37936303
IP : OWN
Cvv : gen
Credits : @YoursPhoenix
```

输出：
```yaml
cards:
  - rule: "37936303xxxxxxx|xx|xx|xxxx"
    sites:
      - name: "Landingsite"
        domain: "landingsite.ai"
    ip: "OWN"
    credits: "@YoursPhoenix"
    notes: null
```

### 示例 2：Visa卡（12位已接近16位）
输入：
```
🔥 ChatGPT & Claude bins

453201482956
exp: 12/28
US IP!!

by @BinMaster
```

输出：
```yaml
cards:
  - rule: "453201482956xxxx|12|28|xxx"
    sites:
      - name: "ChatGPT"
        domain: "openai.com"
      - name: "Claude"
        domain: "anthropic.com"
    ip: "US"
    credits: "@BinMaster"
    notes: null
```

### 示例 3：6位BIN补齐（Visa和Mastercard）
输入：
```
Netflix bin: 453201 exp 09/25 US IP
Spotify bin: 531247 UK IP
@CardKing
```

输出：
```yaml
cards:
  - rule: "453201xxxxxxxxxx|09|25|xxx"
    sites:
      - name: "Netflix"
        domain: "netflix.com"
    ip: "US"
    credits: "@CardKing"
    notes: null

  - rule: "531247xxxxxxxxxx|xx|xx|xxx"
    sites:
      - name: "Spotify"
        domain: "spotify.com"
    ip: "UK"
    credits: "@CardKing"
    notes: null
```

### 示例 4：完整16位卡号（不需补齐）
输入：
```
bin 4921850000001234
for hulu, dinsey+, openai
use residential proxy only!!!
don't hit more than 3 times
@leaker
```

输出：
```yaml
cards:
  - rule: "4921850000001234|xx|xx|xxx"
    sites:
      - name: "Hulu"
        domain: "hulu.com"
      - name: "Disney+"
        domain: "disneyplus.com"
      - name: "OpenAI"
        domain: "openai.com"
    ip: "Residential Proxy"
    credits: "@leaker"
    notes: "不要超过3次尝试"
```

### 示例 5：AMEX 8位补齐到15位
输入：
```
bin: 37936303
site: example.com
```

输出：
```yaml
cards:
  - rule: "37936303xxxxxxx|xx|xx|xxxx"
    sites:
      - name: "Example"
        domain: "example.com"
    ip: null
    credits: null
    notes: null
```

## 无效输入

```yaml
cards: []
error: "未识别到有效的BIN信息"


## 错误例子

输入:
```
B!N ALIEXPRESS -5$ 
ALIEXPRESS: (ALIPAY)

54704660138xxxxx
06/29

IP: 🇲🇽

Generate CCN works

Credits: @brt0110
```

输出:
```

```
cards:
  - rule: "547046|xx|29|xxx"
    sites:
      - name: "AliExpress"
        domain: "AliExpress.com"
    ip: MX
    credits: null
    notes: null
```
原因: 截断了消息中的卡号，并且月份错误，正确的rule为 54704660138|06|29|xxx
"""


class BinParser:
    """BIN消息解析服务"""

    @staticmethod
    async def parse_bin_message(
        message_text: str,
        custom_prompt: Optional[str] = None
    ) -> Optional[BinParseResult]:
        """
        解析BIN消息（AI返回YAML后手动解析）

        Args:
            message_text: 原始消息文本
            custom_prompt: 自定义AI提示词（可选）

        Returns:
            BinParseResult对象，如果解析失败返回None
        """

        # 检查AI是否配置
        if not ai_service.is_configured():
            logger.warning("AI服务未配置，无法解析BIN消息")
            return None

        # 限制消息长度（避免token超限）
        if len(message_text) > 2000:
            logger.warning(f"消息过长({len(message_text)}字符)，截断处理")
            message_text = message_text[:2000]

        # 使用自定义prompt或默认prompt
        system_prompt = custom_prompt or DEFAULT_BIN_PROMPT

        try:
            # 调用AI获取YAML格式的响应
            response_text = await ai_service.generate_text(
                prompt=message_text,
                system_prompt=system_prompt,
                temperature=0.3,
                max_tokens=2000
            )

            if not response_text:
                logger.debug("AI未返回任何内容")
                return None

            # 提取YAML代码块（支持 ```yaml 或 ``` 包裹）
            yaml_match = re.search(r'```(?:yaml)?\n(.*?)\n```', response_text, re.DOTALL)
            if yaml_match:
                yaml_text = yaml_match.group(1)
            else:
                # 如果没有代码块，尝试直接解析整个响应
                yaml_text = response_text

            # 解析YAML
            try:
                data = yaml.safe_load(yaml_text)
            except yaml.YAMLError as e:
                logger.warning(f"YAML解析失败: {e}\n原始内容:\n{yaml_text[:500]}")
                return None

            # 验证数据结构
            if not isinstance(data, dict):
                logger.warning(f"YAML格式错误：根对象不是字典")
                return None

            # 检查是否有错误信息
            if 'error' in data and data['error']:
                logger.info(f"AI识别结果: {data['error']}")
                return BinParseResult(cards=[], error=data['error'])

            # 解析cards列表
            cards_data = data.get('cards', [])
            if not cards_data:
                logger.debug("AI未识别到BIN信息")
                return BinParseResult(cards=[], error=None)

            # 转换为Pydantic模型
            cards = []
            for card_data in cards_data:
                try:
                    # 解析sites
                    sites = []
                    for site_data in card_data.get('sites', []):
                        sites.append(BinSiteInfo(
                            name=site_data.get('name', ''),
                            domain=site_data.get('domain', '')
                        ))

                    # 创建BinCardInfo
                    card = BinCardInfo(
                        rule=card_data.get('rule', ''),
                        sites=sites,
                        ip=card_data.get('ip'),
                        credits=card_data.get('credits'),
                        notes=card_data.get('notes')
                    )
                    cards.append(card)
                except Exception as e:
                    logger.warning(f"解析单张卡片失败: {e}, 数据: {card_data}")
                    continue

            if not cards:
                logger.debug("没有成功解析的BIN卡")
                return None

            logger.info(f"成功解析 {len(cards)} 张BIN卡")
            return BinParseResult(cards=cards, error=None)

        except Exception as e:
            logger.exception(f"BIN解析失败: {e}")
            return None

    @staticmethod
    def normalize_domain(domain: str) -> str:
        """
        标准化域名格式

        Examples:
            https://www.example.com/path -> example.com
            HTTP://Example.COM -> example.com
            example.com -> example.com
        """
        if not domain:
            return ""

        domain = domain.lower().strip()
        domain = domain.removeprefix("http://").removeprefix("https://")
        domain = domain.removeprefix("www.")
        domain = domain.split("/")[0]  # 移除路径
        domain = domain.split("?")[0]  # 移除查询参数
        return domain

    @staticmethod
    def extract_rule_prefix(rule: str) -> str:
        """
        从规则中提取前缀（用于快速搜索）

        Examples:
            453201|12|28|xxx -> 453201
            37936303|xx|xx|xxxx -> 37936303
        """
        if not rule:
            return ""

        # 提取第一个管道符之前的数字
        prefix = rule.split("|")[0].strip()
        # 只保留数字
        prefix = ''.join(c for c in prefix if c.isdigit())
        # 最多8位
        return prefix[:8]
