@echo off
chcp 65001 >nul
setlocal enabledelayedexpansion

:: 切换到脚本所在目录
cd /d "%~dp0"

echo ================================================================================
echo              上传到全新 GitHub 仓库
echo ================================================================================
echo.
echo 当前目录：%CD%
echo.
echo 此脚本将：
echo   1. 删除旧的 .git 目录（如果存在）
echo   2. 初始化新的 Git 仓库
echo   3. 配置 Git 用户信息
echo   4. 添加所有文件并提交
echo   5. 推送到 GitHub 新仓库
echo.
pause

:: 步骤 1: 删除旧的 .git 目录
echo.
echo ================================================================================
echo 步骤 1/5: 清理旧的 Git 历史
echo ================================================================================
echo.

if exist ".git" (
    echo 正在删除旧的 .git 目录...
    rmdir /s /q .git
    echo ✅ 已删除旧的 Git 历史
) else (
    echo ℹ️  未找到 .git 目录，跳过清理
)

:: 步骤 2: 配置 Git 用户信息
echo.
echo ================================================================================
echo 步骤 2/5: 配置 Git 用户信息
echo ================================================================================
echo.

set /p GIT_NAME="请输入 Git 用户名 (例如: keyanniao-home): "
if "!GIT_NAME!"=="" (
    echo ❌ 用户名不能为空！
    pause
    exit /b 1
)

set /p GIT_EMAIL="请输入 Git 邮箱 (例如: noreply@github.com): "
if "!GIT_EMAIL!"=="" (
    echo ❌ 邮箱不能为空！
    pause
    exit /b 1
)

echo.
echo 将使用以下信息：
echo   用户名: !GIT_NAME!
echo   邮  箱: !GIT_EMAIL!
echo.

:: 步骤 3: 初始化 Git 仓库
echo.
echo ================================================================================
echo 步骤 3/5: 初始化 Git 仓库
echo ================================================================================
echo.

git init
if errorlevel 1 (
    echo ❌ Git 初始化失败！请检查是否安装了 Git
    pause
    exit /b 1
)

echo ✅ Git 仓库初始化成功
echo.

:: 配置用户信息
git config user.name "!GIT_NAME!"
git config user.email "!GIT_EMAIL!"

echo ✅ Git 用户信息配置完成

:: 步骤 4: 添加文件并提交
echo.
echo ================================================================================
echo 步骤 4/5: 添加文件并提交
echo ================================================================================
echo.

:: 确保 .gitignore 存在
if not exist ".gitignore" (
    echo ⚠️  警告：未找到 .gitignore 文件
)

echo 正在添加所有文件...
git add .

if errorlevel 1 (
    echo ❌ 添加文件失败！
    pause
    exit /b 1
)

echo ✅ 文件添加成功
echo.

echo 正在创建初始提交...
git commit -m "Initial commit: Telegram Group Management Bot"

if errorlevel 1 (
    echo ❌ 提交失败！
    pause
    exit /b 1
)

echo ✅ 提交成功
echo.

:: 步骤 5: 推送到 GitHub
echo.
echo ================================================================================
echo 步骤 5/5: 推送到 GitHub
echo ================================================================================
echo.

set /p REPO_URL="请输入 GitHub 仓库 URL (例如: https://github.com/keyanniao-home/tg-management-bot.git): "
if "!REPO_URL!"=="" (
    echo ❌ 仓库 URL 不能为空！
    pause
    exit /b 1
)

echo.
echo 将推送到：!REPO_URL!
echo.
set /p CONFIRM="确认推送？(Y/N): "
if /I not "!CONFIRM!"=="Y" (
    echo 操作已取消
    pause
    exit /b 0
)

echo.
echo 🚀 正在推送到 GitHub...
echo.

:: 添加远程仓库
git remote add origin "!REPO_URL!"

:: 设置默认分支为 main
git branch -M main

:: 推送
git push -u origin main

if errorlevel 1 (
    echo.
    echo ❌ 推送失败！
    echo.
    echo 可能的原因：
    echo   1. 仓库 URL 错误
    echo   2. 没有推送权限（需要配置 Personal Access Token）
    echo   3. 远程仓库不是空的
    echo.
    echo 💡 如果需要配置 Token，请：
    echo   1. GitHub → Settings → Developer settings → Personal access tokens
    echo   2. 生成新 Token（勾选 repo 权限）
    echo   3. 使用 HTTPS 推送时输入 Token 作为密码
    echo.
    pause
    exit /b 1
)

echo.
echo ================================================================================
echo                          ✅ 上传成功！
echo ================================================================================
echo.
echo 📊 仓库信息：
echo   用户名: !GIT_NAME!
echo   邮  箱: !GIT_EMAIL!
echo   远程仓库: !REPO_URL!
echo.
echo 💡 后续操作：
echo   1. 访问 GitHub 检查仓库
echo   2. 查看 Contributors 应该只有一个账号
echo   3. 测试从 GitHub clone 并部署
echo.
echo 🎉 现在您的 GitHub 仓库已经是全新的提交历史了！
echo.
pause
