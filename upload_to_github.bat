@echo off
chcp 65001 >nul
setlocal enabledelayedexpansion

REM ============================================
REM Interactive GitHub Upload Script
REM Repository: https://github.com/keyanniao-home/tg-management-bot.git
REM ============================================

echo.
echo ========================================
echo   GitHub Upload Assistant
echo ========================================
echo.

REM Check if Git is installed
git --version >nul 2>&1
if errorlevel 1 (
    echo [ERROR] Git is not installed!
    echo Please download Git from: https://git-scm.com/download/win
    pause
    exit /b 1
)

echo [OK] Git is installed
echo.

REM Step 1: Check for sensitive files
echo ========================================
echo Step 1: Security Check
echo ========================================
if exist .env (
    echo [WARNING] .env file detected
    echo This file contains sensitive data and will NOT be uploaded
    echo Make sure it's in .gitignore
    echo.
    choice /C YN /M "Continue anyway?"
    if errorlevel 2 exit /b 0
) else (
    echo [OK] No .env file found in root directory
)
echo.

REM Step 2: Check repository status
echo ========================================
echo Step 2: Repository Status
echo ========================================

if not exist .git (
    echo Initializing new Git repository...
    git init
    echo [OK] Repository initialized
) else (
    echo [OK] Git repository already exists
)
echo.

REM Check for uncommitted changes
git diff-index --quiet HEAD -- >nul 2>&1
if errorlevel 1 (
    echo [INFO] You have uncommitted changes
) else (
    git status | find "nothing to commit" >nul
    if not errorlevel 1 (
        echo [INFO] Working tree is clean
    )
)
echo.

REM Step 3: Stage files
echo ========================================
echo Step 3: Adding Files
echo ========================================
echo Adding all files to staging area...
git add .

echo.
echo Files to be committed:
git status --short
echo.

choice /C YN /M "Proceed with commit?"
if errorlevel 2 (
    echo Upload cancelled
    pause
    exit /b 0
)

REM Step 4: Commit
echo.
echo ========================================
echo Step 4: Commit Changes
echo ========================================

set /p COMMIT_MSG="Enter commit message (or press Enter for default): "
if "%COMMIT_MSG%"=="" (
    set "COMMIT_MSG=Initial commit: Full-featured Telegram Group Management Bot"
)

git commit -m "%COMMIT_MSG%"
if errorlevel 1 (
    echo [INFO] No changes to commit
)
echo.

REM Step 5: Configure remote
echo ========================================
echo Step 5: Remote Repository
echo ========================================

REM Remove existing origin if any
git remote remove origin >nul 2>&1

REM Set new origin
git remote add origin https://github.com/keyanniao-home/tg-management-bot.git
git branch -M main

echo [OK] Remote repository configured
echo.

REM Step 6: Authentication Setup
echo ========================================
echo Step 6: GitHub Authentication
echo ========================================
echo.
echo This repository is in an ORGANIZATION.
echo You will need to provide authentication credentials.
echo.
echo Personal Access Token Setup:
echo   1. Visit: https://github.com/settings/tokens
echo   2. Click 'Generate new token (classic)'
echo   3. Check these permissions:
echo      [x] repo (all checkboxes)
echo      [x] read:org (under admin:org)
echo   4. Generate and copy the token
echo.

choice /C 12 /M "Choose authentication method: [1] Manual Input [2] Git Credential Helper"

if errorlevel 2 goto USE_CREDENTIAL_HELPER
if errorlevel 1 goto MANUAL_INPUT

:MANUAL_INPUT
echo.
echo ========================================
echo Manual Authentication Input
echo ========================================
echo.
set /p GH_USERNAME="Enter your GitHub username: "
set /p GH_TOKEN="Enter your Personal Access Token: "

if "%GH_USERNAME%"=="" (
    echo [ERROR] Username cannot be empty
    pause
    exit /b 1
)

if "%GH_TOKEN%"=="" (
    echo [ERROR] Token cannot be empty
    pause
    exit /b 1
)

REM Update remote URL with credentials
git remote set-url origin https://%GH_USERNAME%:%GH_TOKEN%@github.com/keyanniao-home/tg-management-bot.git

echo [OK] Credentials configured
goto PUSH_TO_GITHUB

:USE_CREDENTIAL_HELPER
echo.
echo ========================================
echo Git Credential Helper
echo ========================================
echo.
echo Git will prompt you for:
echo   Username: your_github_username
echo   Password: your_personal_access_token
echo.
echo Credentials will be saved for future use.
echo.
git config credential.helper store
pause
goto PUSH_TO_GITHUB

:PUSH_TO_GITHUB
REM Step 7: Push to GitHub
echo.
echo ========================================
echo Step 7: Pushing to GitHub
echo ========================================
echo.
echo Pushing to remote repository...
echo.

git push -u origin main

if errorlevel 1 (
    echo.
    echo ========================================
    echo [ERROR] Push Failed!
    echo ========================================
    echo.
    echo Common issues:
    echo   1. Wrong username or token
    echo   2. Token doesn't have 'read:org' permission
    echo   3. Not a member of the organization
    echo   4. Repository doesn't exist
    echo   5. Token expired
    echo.
    echo Please check your credentials and try again.
    echo.
    
    REM Clean up credentials if manual input was used
    if defined GH_TOKEN (
        git remote set-url origin https://github.com/keyanniao-home/tg-management-bot.git
        echo [INFO] Credentials removed from remote URL for security
    )
    
    pause
    exit /b 1
)

REM Clean up credentials from URL if manual input was used
if defined GH_TOKEN (
    git remote set-url origin https://github.com/keyanniao-home/tg-management-bot.git
    echo [INFO] Credentials removed from remote URL for security
)

REM Success!
echo.
echo ========================================
echo   SUCCESS! Upload Complete!
echo ========================================
echo.
echo Your repository is now available at:
echo https://github.com/keyanniao-home/tg-management-bot
echo.
echo Next steps:
echo   - Visit the repository to verify
echo   - Check that .env is NOT visible
echo   - Add a LICENSE file (recommended: MIT)
echo   - Add repository description and topics
echo   - Star your own repo! ;)
echo.
pause
