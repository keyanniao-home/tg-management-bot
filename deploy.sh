#!/bin/bash
# Telegram Bot 一键部署脚本（Linux服务器）
# 使用方法：chmod +x deploy.sh && ./deploy.sh

set -e  # 遇到错误立即退出

echo "=========================================="
echo "  Telegram Bot 自动部署脚本"
echo "=========================================="
echo ""

# 检查系统
if [[ ! -f /etc/os-release ]]; then
    echo "❌ 无法识别的Linux系统"
    exit 1
fi

# 检查Docker
echo "📦 检查Docker..."
if ! command -v docker &> /dev/null; then
    echo "⚠️  Docker未安装，正在安装..."
    curl -fsSL https://get.docker.com -o get-docker.sh
    sudo sh get-docker.sh
    sudo usermod -aG docker $USER
    echo "✅ Docker安装完成"
    echo "⚠️  请重新登录后再运行此脚本（以激活docker组权限）"
    exit 0
else
    echo "✅ Docker已安装: $(docker --version)"
fi

# 检查Docker Compose
echo "📦 检查Docker Compose..."
if ! command -v docker-compose &> /dev/null; then
    echo "⚠️  Docker Compose未安装，正在安装..."
    sudo curl -L "https://github.com/docker/compose/releases/latest/download/docker-compose-$(uname -s)-$(uname -m)" -o /usr/local/bin/docker-compose
    sudo chmod +x /usr/local/bin/docker-compose
    echo "✅ Docker Compose安装完成"
else
    echo "✅ Docker Compose已安装: $(docker-compose --version)"
fi

# 检查.env文件
if [[ ! -f .env ]]; then
    echo ""
    echo "⚠️  未找到.env配置文件"
    echo "正在从.env.example创建..."
    cp .env.example .env
    echo ""
    echo "=========================================="
    echo "  ⚠️  请立即编辑.env文件！"
    echo "=========================================="
    echo ""
    echo "必须配置以下项："
    echo "1. TELEGRAM_BOT_TOKEN=你的Bot_Token"
    echo "2. DATABASE_PASSWORD=强密码"
    echo "3. LLM_API_KEY=你的OpenAI_Key（如需消息总结功能）"
    echo ""
    echo "使用以下命令编辑："
    echo "  nano .env"
    echo "或"
    echo "  vim .env"
    echo ""
    read -p "配置完成后按Enter继续，或Ctrl+C退出..." 
fi

# 验证必要配置
echo ""
echo "🔍 验证配置..."
source .env

if [[ -z "$TELEGRAM_BOT_TOKEN" ]] || [[ "$TELEGRAM_BOT_TOKEN" == "your_bot_token_here" ]]; then
    echo "❌ 错误：未配置TELEGRAM_BOT_TOKEN"
    echo "请编辑.env文件并设置正确的Bot Token"
    exit 1
fi

if [[ "$DATABASE_PASSWORD" == "your_password_here" ]]; then
    echo "⚠️  警告：使用默认数据库密码不安全！"
    read -p "是否继续？(y/n) " -n 1 -r
    echo
    if [[ ! $REPLY =~ ^[Yy]$ ]]; then
        exit 1
    fi
fi

echo "✅ 配置验证通过"

# 停止旧容器（如果存在）
echo ""
echo "🛑 停止旧容器..."
docker-compose down 2>/dev/null || true

# 构建和启动
echo ""
echo "🚀 启动Bot..."
docker-compose up -d --build

# 等待启动
echo ""
echo "⏳ 等待Bot启动..."
sleep 5

# 检查状态
echo ""
echo "📊 服务状态："
docker-compose ps

# 显示日志
echo ""
echo "=========================================="
echo "  📋 Bot启动日志（最后20行）"
echo "=========================================="
docker-compose logs --tail=20 bot

echo ""
echo "=========================================="
echo "  ✅ 部署完成！"
echo "=========================================="
echo ""
echo "🔑 请从上方日志中找到初始化密钥："
echo "   🔑 初始化密钥（请妥善保管）: xxxxxxxx-xxxx-xxxx-xxxx-xxxxxxxxxxxx"
echo ""
echo "📝 下一步："
echo "1. 将Bot添加到Telegram群组"
echo "2. 设置Bot为管理员"
echo "3. 在群组发送: /kobe_init 你的初始化密钥"
echo "4. 创建分类和标签（参考README.md）"
echo ""
echo "📖 常用命令："
echo "  查看日志:   docker-compose logs -f bot"
echo "  重启Bot:    docker-compose restart bot"
echo "  停止Bot:    docker-compose down"
echo "  查看状态:   docker-compose ps"
echo ""
echo "📚 完整文档："
echo "  - DOCKER_DEPLOY.md  : Docker部署详细说明"
echo "  - README.md         : 功能说明和使用指南"
echo "  - docs/COMMANDS.md  : 命令参考手册"
echo ""
