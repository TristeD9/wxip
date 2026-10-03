"""应用运行配置：集中从环境变量和 .env 读取，避免散落的硬编码。"""

from __future__ import annotations

from pathlib import Path

from pydantic import Field
from pydantic_settings import BaseSettings, SettingsConfigDict

PROJECT_ROOT = Path(__file__).resolve().parents[2]


class Settings(BaseSettings):
    """后端运行配置，所有字段都可用 APP_ 前缀的环境变量覆盖。"""

    model_config = SettingsConfigDict(env_file=".env", env_prefix="APP_", extra="ignore")

    data_dir: Path = Field(default=PROJECT_ROOT / "data")
    database_filename: str = "app.sqlite3"
    frontend_dir: Path = Field(default=PROJECT_ROOT / "frontend")

    secret_key: str = "change-me-before-deploy"
    session_ttl_seconds: int = 12 * 3600
    cors_origins: list[str] = Field(
        default_factory=lambda: [
            "http://localhost:5173",
            "http://127.0.0.1:5173",
        ]
    )

    auto_sync_enabled: bool = True
    sync_interval_seconds: int = 300

    browser_headless: bool = True
    browser_channel: str = ""
    browser_timeout_ms: int = 45_000
    ikuai_timeout_seconds: float = 10.0
    http_timeout_seconds: float = 10.0

    log_level: str = "INFO"

    @property
    def database_path(self) -> Path:
        """返回 SQLite 数据库文件的绝对路径。"""
        return self.data_dir / self.database_filename

    @property
    def wecom_state_path(self) -> Path:
        """返回企业微信管理后台登录态的持久化路径。"""
        return self.data_dir / "wecom_state.json"

    def ensure_directories(self) -> None:
        """创建运行期需要的目录，重复调用无副作用。"""
        self.data_dir.mkdir(parents=True, exist_ok=True)

