#!/bin/bash
# ============================================
# Interactive GitHub Upload Script
# Repository: https://github.com/keyanniao-home/tg-management-bot.git
# ============================================

set -e

# Colors
RED='\033[0;31m'
GREEN='\033[0;32m'
YELLOW='\033[1;33m'
BLUE='\033[0;34m'
NC='\033[0m' # No Color

echo ""
echo "========================================"
echo "  GitHub Upload Assistant"
echo "========================================"
echo ""

# Check if Git is installed
if ! command -v git &> /dev/null; then
    echo -e "${RED}[ERROR]${NC} Git is not installed!"
    echo "Please install Git first"
    exit 1
fi

echo -e "${GREEN}[OK]${NC} Git is installed"
echo ""

# Step 1: Check for sensitive files
echo "========================================"
echo "Step 1: Security Check"
echo "========================================"
if [ -f .env ]; then
    echo -e "${YELLOW}[WARNING]${NC} .env file detected"
    echo "This file contains sensitive data and will NOT be uploaded"
    echo "Make sure it's in .gitignore"
    echo ""
    read -p "Continue anyway? (y/n) " -n 1 -r
    echo ""
    if [[ ! $REPLY =~ ^[Yy]$ ]]; then
        exit 0
    fi
else
    echo -e "${GREEN}[OK]${NC} No .env file found in root directory"
fi
echo ""

# Step 2: Check repository status
echo "========================================"
echo "Step 2: Repository Status"
echo "========================================"

if [ ! -d .git ]; then
    echo "Initializing new Git repository..."
    git init
    echo -e "${GREEN}[OK]${NC} Repository initialized"
else
    echo -e "${GREEN}[OK]${NC} Git repository already exists"
fi
echo ""

# Step 3: Stage files
echo "========================================"
echo "Step 3: Adding Files"
echo "========================================"
echo "Adding all files to staging area..."
git add .

echo ""
echo "Files to be committed:"
git status --short
echo ""

read -p "Proceed with commit? (y/n) " -n 1 -r
echo ""
if [[ ! $REPLY =~ ^[Yy]$ ]]; then
    echo "Upload cancelled"
    exit 0
fi

# Step 4: Commit
echo ""
echo "========================================"
echo "Step 4: Commit Changes"
echo "========================================"

read -p "Enter commit message (or press Enter for default): " COMMIT_MSG
if [ -z "$COMMIT_MSG" ]; then
    COMMIT_MSG="Initial commit: Full-featured Telegram Group Management Bot"
fi

git commit -m "$COMMIT_MSG"
echo -e "${GREEN}[OK]${NC} Changes committed"
echo ""

# Step 5: Configure remote
echo "========================================"
echo "Step 5: Remote Repository"
echo "========================================"

# Remove existing origin if any
git remote remove origin 2>/dev/null || true

# Set new origin
git remote add origin https://github.com/keyanniao-home/tg-management-bot.git
git branch -M main

echo -e "${GREEN}[OK]${NC} Remote repository configured"
echo ""

# Step 6: Authentication Setup
echo "========================================"
echo "Step 6: Authentication"
echo "========================================"
echo ""
echo "This repository is in an organization, so you need:"
echo "  1. Your GitHub username"
echo "  2. A Personal Access Token (NOT your password!)"
echo ""
echo "To create a token (if you don't have one):"
echo "  1. Visit: https://github.com/settings/tokens"
echo "  2. Click 'Generate new token (classic)'"
echo "  3. Check these permissions:"
echo "     - repo (all)"
echo "     - read:org"
echo "  4. Generate and copy the token"
echo ""
echo -e "${YELLOW}[IMPORTANT]${NC} When Git asks for password, paste your TOKEN!"
echo ""

read -p "Do you have your GitHub username and token ready? (y/n) " -n 1 -r
echo ""
if [[ ! $REPLY =~ ^[Yy]$ ]]; then
    echo ""
    echo "Please create your token first, then run this script again."
    exit 0
fi

# Step 7: Push to GitHub
echo ""
echo "========================================"
echo "Step 7: Pushing to GitHub"
echo "========================================"
echo ""
echo "You will be prompted for:"
echo "  Username: your_github_username"
echo "  Password: your_personal_access_token (paste it)"
echo ""
read -p "Press Enter to continue..."

echo "Pushing to GitHub..."
if git push -u origin main; then
    # Success!
    echo ""
    echo "========================================"
    echo -e "${GREEN}  SUCCESS! Upload Complete!${NC}"
    echo "========================================"
    echo ""
    echo "Your repository is now available at:"
    echo -e "${BLUE}https://github.com/keyanniao-home/tg-management-bot${NC}"
    echo ""
    echo "Next steps:"
    echo "  - Visit the repository to verify"
    echo "  - Add a LICENSE file (recommended: MIT)"
    echo "  - Check that .env is NOT visible"
    echo "  - Star your own repo! ;)"
    echo ""
else
    echo ""
    echo "========================================"
    echo -e "${RED}[ERROR] Push Failed!${NC}"
    echo "========================================"
    echo ""
    echo "Common issues:"
    echo "  1. Wrong username or token"
    echo "  2. Token doesn't have 'read:org' permission"
    echo "  3. Not a member of the organization"
    echo "  4. Repository doesn't exist"
    echo ""
    echo "Please check and try again"
    exit 1
fi
