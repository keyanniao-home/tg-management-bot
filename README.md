# 📦 Telegram 群组管理机器人

一个功能完整的 Telegram 群组管理机器人，集成了资源管理、AI 总结、积分系统、私信转发等多项功能。

## ✨ 核心功能

### 📁 资源管理系统
- **文件上传与分类**: 支持所有类型文件的上传，自动分类和标签管理
- **智能搜索**: 按关键词、分类、标签搜索资源
- **可视化面板**: 提供友好的资源浏览和管理界面
- **文件转发**: Bot 可直接发送文件，无需跳转聊天记录
- **完整删除**: 支持同时删除 Telegram 消息和数据库记录
- **权限控制**: 仅上传者和管理员可删除资源

### 🤖 AI 功能
- **智能总结**: 使用 AI 总结指定用户或全群的聊天内容
- **自定义摘要**: 配置每日推送时间和内容
- **深度分析**: 支持话题提取、情绪分析等高级功能

### 💬 私信系统 (DM)
- **群内私信**: 成员间可通过 Bot 转发私信
- **隐私保护**: 私信内容仅发送者和接收者可见
- **消息追踪**: 查看收到的所有私信记录

### 📊 积分与签到
- **积分奖励**: 发消息、上传资源、签到均可获得积分
- **排行榜**: 展示群组积分排行
- **防刷机制**: 每日消息积分上限，防止刷分

### 🛡️ 群组管理
- **成员管理**: 封禁、踢出、禁言等基础管理功能
- **频道绑定**: 支持话题群组（Forum）和频道绑定
- **消息记录**: 自动记录所有消息，支持查询历史

### 🎯 其他功能
- **查询面板**: 可视化查询指定用户的消息记录
- **自动删除**: 支持命令消息的自动删除
- **日志系统**: 完整的日志记录和错误追踪

---

## 🚀 快速开始

### 环境要求

- **Docker** >= 20.10
- **Docker Compose** >= 2.0
- **Telegram Bot Token** (从 [@BotFather](https://t.me/BotFather) 获取)
- **PostgreSQL** (通过 Docker 自动部署)

### 安装步骤

#### 1. 克隆项目

```bash
git clone https://github.com/keyanniao-home/tg-management-bot.git
cd tg-management-bot
```

#### 2. 配置环境变量

复制 `.env.example` 并重命名为 `.env`：

```bash
cp .env.example .env
```

编辑 `.env` 文件，填写必要配置：

```env
# Telegram Bot 配置 (必填)
TELEGRAM_BOT_TOKEN=your_bot_token_here

# 数据库配置 (必填)
DATABASE_PASSWORD=your_secure_password_here

# AI 服务配置 (可选，用于 AI 总结功能)
AI_ENABLED=true
AI_BASE_URL=https://api.openai.com/v1
AI_API_KEY=your_openai_api_key
AI_MODEL_ID=gpt-4

# LLM 配置 (可选，用于消息总结)
LLM_ENABLED=true
LLM_BASE_URL=https://api.openai.com/v1
LLM_API_KEY=your_openai_api_key
LLM_MODEL=gpt-4
```

#### 3. 启动服务

```bash
# 构建并启动所有服务
docker-compose up -d

# 查看日志
docker-compose logs -f bot
```

#### 4. 初始化数据库

首次启动时，数据库会自动初始化。如需手动初始化：

```bash
docker-compose exec postgres psql -U postgres -d telegram_group_management
```

---

## ⚙️ 配置说明

### Bot Token 获取

1. 在 Telegram 中找到 [@BotFather](https://t.me/BotFather)
2. 发送 `/newbot` 创建新机器人
3. 按提示设置名称和用户名
4. 复制获得的 Token 到 `.env` 文件

### 管理员设置

获取自己的 User ID：
1. 将 Bot 添加到群组
2. 在群组中发送 `/id`
3. Bot 会回复您的 User ID
4. 将 ID 添加到 `.env` 的 `ADMIN_USER_IDS`

### AI 功能配置

支持的 AI 服务：
- **OpenAI** (GPT-3.5/GPT-4)
- **DeepSeek**
- **任何兼容 OpenAI API 的服务**

配置示例：

```env
# OpenAI
AI_API_BASE_URL=https://api.openai.com/v1
AI_API_KEY=sk-...
AI_MODEL=gpt-4

# DeepSeek
AI_API_BASE_URL=https://api.deepseek.com/v1
AI_API_KEY=sk-...
AI_MODEL=deepseek-chat
```

---

## 🎯 首次使用 - Bot 初始化

**⚠️ 重要：Bot 部署后，必须先在群组中初始化才能使用所有功能！**

### 步骤1：获取初始化密钥

Bot 启动时会在日志中显示初始化密钥。查看方式：

```bash
docker-compose logs bot | grep "初始化密钥"
```

您会看到类似这样的输出：
```
🔑 初始化密钥（请妥善保管）: 5cc1eb53-8b38-4681-a1c5-f37394238147
```

### 步骤2：在群组中初始化

1. 将 Bot 添加到您的 Telegram 群组
2. 确保 Bot 具有**管理员权限**
3. 在群组中发送初始化命令：

```
/init 5cc1eb53-8b38-4681-a1c5-f37394238147
```

（将上面的密钥替换为您的实际密钥）

### 步骤3：验证初始化

初始化成功后，Bot 会回复确认消息。此时您可以使用 `/help` 查看所有可用命令。

### 🔐 安全提示

- **初始化密钥仅能使用一次** - 初始化后密钥会失效
- **妥善保管密钥** - 任何人拿到密钥都能成为超级管理员
- **建议在初始化后删除包含密钥的消息**

### ❓ 忘记密钥怎么办？

如果忘记或丢失密钥，可以重启 Bot 获取新密钥：

```bash
docker-compose restart bot
docker-compose logs bot | grep "初始化密钥"
```

⚠️ 注意：重启会生成新密钥，但已初始化的群组不受影响。

---

## 📖 使用指南

### 资源管理

#### 上传文件

```
1. 在群组中发送文件
2. 回复文件并发送 /upload
3. 按提示选择分类
4. 选择或创建标签
5. 输入描述
6. 完成上传
```

#### 浏览资源

```
/resources - 打开资源库
```

在资源库中可以：
- 📤 发送文件 - 直接获取文件
- 📂 按分类筛选
- 🏷️ 按标签筛选
- 🗑️ 删除资源（需要权限）

#### 搜索资源

```
/search 关键词
```

### 管理面板

```
/manage_categories  # 分类管理（管理员）
/manage_tags        # 标签管理（管理员）
/manage_resources   # 资源管理（管理员）
```

### AI 总结

```
/ai_summary                    # 打开 AI 总结面板
/query_messages                # 查询指定用户消息
/digest_config                 # 配置每日推送
```

### 私信系统

```
# 激活 DM 功能
1. 私聊 Bot 发送 /start

# 发送私信
/dm <user_id> <消息内容>

# 查看收到的私信
/my_dms
```

### 积分签到

```
/checkin       # 每日签到
/leaderboard   # 积分排行榜
```

---

## 🔧 高级配置

### 数据库迁移

如需修改数据库结构，执行：

```bash
# 进入数据库容器
docker-compose exec postgres psql -U postgres -d telegram_group_management

# 执行 SQL
ALTER TABLE table_name ADD COLUMN new_column TYPE;

# 退出
\q
```

### 备份数据

```bash
# 备份数据库
docker-compose exec postgres pg_dump -U postgres telegram_group_management > backup.sql

# 恢复数据库
docker-compose exec -T postgres psql -U postgres telegram_group_management < backup.sql
```

### 查看日志

```bash
# 实时日志
docker-compose logs -f bot

# 查看最近100行
docker-compose logs --tail=100 bot

# 查看错误日志
docker-compose logs bot | grep ERROR
```

---

## 📁 项目结构

```
telegram_group_management_temp/
├── app/
│   ├── database/           # 数据库连接和迁移
│   ├── handlers/           # 命令和回调处理器
│   │   ├── bind.py        # 频道绑定
│   │   ├── commands.py    # 基础命令
│   │   ├── dm_handlers.py # 私信系统
│   │   ├── resource_handlers.py              # 资源管理
│   │   ├── resource_management_handlers.py   # 资源管理面板
│   │   ├── category_management_handlers.py   # 分类管理
│   │   ├── ai_summary_handlers.py            # AI 总结
│   │   └── ...
│   ├── models/            # 数据模型
│   ├── services/          # 业务逻辑层
│   └── utils/             # 工具函数
├── migrations/            # 数据库迁移脚本
├── docker-compose.yml     # Docker 配置
├── Dockerfile            # Bot 镜像构建
├── requirements.txt      # Python 依赖
├── .env.example          # 环境变量示例
└── README.md            # 本文档
```

---

## 🐛 常见问题

### Q: Bot 无响应？

**A:** 检查以下几点：
1. **确认群组已初初化** - 发送 `/kobe_init <密钥>` 初始化群组
2. `docker-compose logs -f bot` 查看是否有错误
3. 确认 `TELEGRAM_BOT_TOKEN` 配置正确
4. 确认 Bot 已添加到群组且有**管理员权限**
5. 检查 `DATABASE_PASSWORD` 是否在 `.env` 中正确配置

### Q: 数据库连接失败？

**A:** 
```bash
# 重启数据库
docker-compose restart postgres

# 检查数据库状态
docker-compose exec postgres pg_isready
```

### Q: AI 总结不工作？

**A:** 
1. 确认 `.env` 中配置了正确的 AI API
2. 检查 API Key 是否有效
3. 查看日志中是否有 API 错误

### Q: 上传文件失败？

**A:**
1. 检查文件大小是否超过 Telegram 限制（2GB）
2. 确认 Bot 有足够的存储空间
3. 查看日志中的具体错误信息

### Q: 权限错误？

**A:**
1. 确认管理员 ID 已添加到 `ADMIN_USER_IDS`
2. Bot 需要在群组中具有管理员权限
3. 某些功能需要 Bot 有删除消息权限

---

## 🔄 更新日志

### v1.0.0 (2026-01-17)

**新功能**:
- ✅ 完整的资源管理系统
- ✅ AI 智能总结
- ✅ 私信转发系统
- ✅ 积分与签到
- ✅ 多个可视化管理面板
- ✅ 文件直接发送功能
- ✅ 完整的删除功能（消息+数据库）

**修复**:
- 🐛 修复 group_id 字段溢出问题
- 🐛 修复外键约束错误
- 🐛 优化标签选择体验
- 🐛 修复 DM 系统命令引用

---

## 🤝 贡献指南

欢迎提交 Issue 和 Pull Request！

### 开发环境设置

```bash
# 克隆项目
git clone https://github.com/your-username/telegram-group-bot.git

# 创建虚拟环境
python -m venv venv
source venv/bin/activate  # Linux/Mac
# venv\Scripts\activate   # Windows

# 安装依赖
pip install -r requirements.txt

# 运行测试
python -m pytest
```

---

## 📄 许可证

本项目采用 MIT 许可证 - 详见 [LICENSE](LICENSE) 文件

---

## TODO List

- [ ] 优化BOT总结系统提示词
- [ ] 优化删除逻辑
- [ ] 新建关联web面板方便查看管理群文件资源
- [ ] 新建其他榜单

## 🙏 致谢

- [python-telegram-bot](https://github.com/python-telegram-bot/python-telegram-bot) - Telegram Bot API 库
- [SQLModel](https://github.com/tiangolo/sqlmodel) - SQL 数据库 ORM
- [Loguru](https://github.com/Delgan/loguru) - 优雅的日志库
科研鸟与wdy的所有支持的大佬们-小爱佬、Kar佬、F佬、韩神、BS佬
---

## 📞 支持

- 📧 Email: your-email@example.com
- 💬 Telegram: [keyanniao](https://t.me/my_username)
- 🐛 Issues: [keyanniao](https://github.com/keyanniao/tg-managenment-bot/issues)

---

**⭐ 如果这个项目对你有帮助，请给个 Star！**
