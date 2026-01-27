from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    model_config = SettingsConfigDict(
        env_file=".env",
        env_file_encoding="utf-8",
        case_sensitive=False,
        extra="ignore"
    )

    telegram_bot_token: str

    # 全局白名单（逗号分隔的用户ID）
    global_whitelist: str = ""

    # User Bot 配置（可选，用于补充 Bot API 功能）
    # 需要先运行 userbot_login.py 脚本登录
    userbot_enabled: bool = False
    userbot_api_id: int = 0
    userbot_api_hash: str = ""
    userbot_session_name: str = "userbot"

    # AI 配置（OpenAI 兼容接口）- 用于用户画像分析
    ai_enabled: bool = False
    ai_base_url: str = "https://api.openai.com/v1"
    ai_api_key: str = ""
    ai_model_id: str = "gpt-4"

    # LLM 配置（OpenAI 兼容接口）- 用于消息总结
    llm_enabled: bool = False
    llm_base_url: str = "https://api.openai.com/v1"
    llm_api_key: str = ""
    llm_model: str = "gpt-4o-mini"

    # 每日总结配置
    daily_summary_enabled: bool = False
    daily_summary_time: str = "09:00"  # HH:MM 格式
    daily_summary_timezone: str = "Asia/Shanghai"

    # 积分系统配置
    points_enabled: bool = True

    # BIN信息查询API
    bin_info_url: str = "https://bin.keyanniao.com/bin"

    database_host: str = "localhost"
    database_port: int = 5432
    database_name: str = "telegram_group_management"
    database_user: str = "postgres"
    database_password: str

    @property
    def database_url(self) -> str:
        return f"postgresql://{self.database_user}:{self.database_password}@{self.database_host}:{self.database_port}/{self.database_name}"

    @property
    def global_whitelist_ids(self) -> list[int]:
        """解析全局白名单为整数列表"""
        if not self.global_whitelist:
            return []
        return [int(id.strip()) for id in self.global_whitelist.split(",") if id.strip().isdigit()]

    @property
    def userbot_session_path(self) -> str:
        """获取 User Bot Session 文件路径"""
        from pathlib import Path
        return str(Path("sessions") / self.userbot_session_name)

    @property
    def is_userbot_configured(self) -> bool:
        """检查 User Bot 是否配置并启用"""
        from pathlib import Path
        session_file = Path(f"{self.userbot_session_path}.session")
        return bool(
            self.userbot_enabled
            and self.userbot_api_id
            and self.userbot_api_hash
            and session_file.exists()
        )

    @property
    def is_ai_configured(self) -> bool:
        """检查 AI 功能是否配置并启用"""
        return bool(
            self.ai_enabled
            and self.ai_api_key
            and self.ai_model_id
        )

    @property
    def is_llm_configured(self) -> bool:
        """检查 LLM 功能是否配置并启用"""
        return bool(
            self.llm_enabled
            and self.llm_api_key
            and self.llm_model
        )


settings = Settings()
