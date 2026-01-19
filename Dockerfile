FROM ghcr.io/astral-sh/uv:python3.12-trixie-slim

WORKDIR /app

ENV PYTHONUNBUFFERED=1

# 安装 git 和 postgresql-client (用于等待数据库启动)
RUN apt-get update && apt-get install -y git postgresql-client && rm -rf /var/lib/apt/lists/*

COPY pyproject.toml uv.lock ./
COPY . .

RUN uv sync --frozen

# 添加启动脚本
RUN echo '#!/bin/sh\nset -e\nuntil pg_isready -h "$DATABASE_HOST" -U "$DATABASE_USER"; do\n  echo "Waiting for PostgreSQL..."\n  sleep 2\ndone\nexec uv run python main.py' > /app/entrypoint.sh && chmod +x /app/entrypoint.sh

CMD ["/app/entrypoint.sh"]
