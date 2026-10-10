"""SQLite 持久化：保存配置、应用清单、IP 观测与同步历史。"""

from __future__ import annotations

import json
import sqlite3
import threading
from collections.abc import Iterator
from contextlib import contextmanager
from datetime import datetime, timezone
from pathlib import Path

from app.models import (
    AdminAccount,
    IKuaiSettings,
    PublicIpObservation,
    RequestTemplate,
    SyncSettings,
    SyncSummary,
    WeComApp,
)

SETTING_IKUAI = "ikuai_settings"
SETTING_TEMPLATE = "wecom_request_template"
SETTING_READ_TEMPLATE = "wecom_read_template"
SETTING_SYNC = "sync_settings"
SETTING_WECOM_APPS_URL = "wecom_apps_url"

DEFAULT_WECOM_APPS_URL = "https://work.weixin.qq.com/wework_admin/frame#apps"

_SCHEMA = """
CREATE TABLE IF NOT EXISTS settings (
    key TEXT PRIMARY KEY,
    value TEXT NOT NULL
);
CREATE TABLE IF NOT EXISTS wecom_apps (
    agent_id TEXT PRIMARY KEY,
    name TEXT NOT NULL,
    console_app_id TEXT,
    last_synced_ip TEXT,
    last_synced_at TEXT,
    current_trusted_ips TEXT,
    trusted_ip_checked_at TEXT,
    last_error TEXT
);
CREATE TABLE IF NOT EXISTS public_ip_observations (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    ip TEXT NOT NULL,
    source TEXT NOT NULL,
    checked_at TEXT NOT NULL
);
CREATE TABLE IF NOT EXISTS sync_events (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    started_at TEXT NOT NULL,
    finished_at TEXT NOT NULL,
    public_ip TEXT,
    status TEXT NOT NULL,
    message TEXT NOT NULL,
    results TEXT NOT NULL
);
CREATE TABLE IF NOT EXISTS admins (
    username TEXT PRIMARY KEY,
    password_hash TEXT NOT NULL,
    created_at TEXT NOT NULL,
    updated_at TEXT NOT NULL
);
"""


class AppStorage:
    """封装所有 SQLite 读写，调用方只面向模型对象。"""

    def __init__(self, database_path: Path) -> None:
        self._database_path = database_path
        self._write_lock = threading.Lock()

    def initialize(self) -> None:
        """建库建表，重复调用无副作用。"""
        self._database_path.parent.mkdir(parents=True, exist_ok=True)
        with self._connect() as connection:
            connection.executescript(_SCHEMA)
            _migrate_schema(connection)

    def get_ikuai_settings(self) -> IKuaiSettings | None:
        """读取 iKuai 连接配置，未配置时返回 None。"""
        stored = self._get_json(SETTING_IKUAI)
        return IKuaiSettings.model_validate(stored) if stored else None

    def save_ikuai_settings(self, settings: IKuaiSettings) -> None:
        """覆盖保存 iKuai 连接配置。"""
        self._set_json(SETTING_IKUAI, settings.model_dump())

    def get_request_template(self) -> RequestTemplate | None:
        """读取企业微信可信 IP 请求模板，未录制时返回 None。"""
        stored = self._get_json(SETTING_TEMPLATE)
        return RequestTemplate.model_validate(stored) if stored else None

    def save_request_template(self, template: RequestTemplate) -> None:
        """覆盖保存请求模板。"""
        self._set_json(SETTING_TEMPLATE, template.model_dump())

    def get_read_template(self) -> RequestTemplate | None:
        """读取"查询当前可信 IP"的请求模板，未录制时返回 None。"""
        stored = self._get_json(SETTING_READ_TEMPLATE)
        return RequestTemplate.model_validate(stored) if stored else None

    def save_read_template(self, template: RequestTemplate) -> None:
        """覆盖保存查询可信 IP 的请求模板。"""
        self._set_json(SETTING_READ_TEMPLATE, template.model_dump())

    def get_wecom_apps_url(self) -> str:
        """读取企业微信应用管理页地址，用于适配后台改版。"""
        stored = self._get_json(SETTING_WECOM_APPS_URL)
        if not stored:
            return DEFAULT_WECOM_APPS_URL
        return str(stored.get("url") or DEFAULT_WECOM_APPS_URL)

    def save_wecom_apps_url(self, url: str) -> None:
        """保存企业微信应用管理页地址。"""
        self._set_json(SETTING_WECOM_APPS_URL, {"url": url})

    def get_sync_settings(self, default: SyncSettings) -> SyncSettings:
        """读取自动同步设置，未配置时返回默认值。"""
        stored = self._get_json(SETTING_SYNC)
        return SyncSettings.model_validate(stored) if stored else default

    def save_sync_settings(self, settings: SyncSettings) -> None:
        """覆盖保存自动同步设置。"""
        self._set_json(SETTING_SYNC, settings.model_dump())

    def count_admins(self) -> int:
        """返回管理员账号数量，用于判断是否需要走首次初始化。"""
        with self._connect() as connection:
            row = connection.execute("SELECT COUNT(*) AS total FROM admins").fetchone()
        return int(row["total"])

    def list_admin_usernames(self) -> list[str]:
        """按用户名排序返回管理员用户名，供运维命令查看。"""
        with self._connect() as connection:
            rows = connection.execute("SELECT username FROM admins ORDER BY username").fetchall()
        return [row["username"] for row in rows]

    def get_admin(self, username: str) -> AdminAccount | None:
        """按用户名读取管理员账号。"""
        with self._connect() as connection:
            row = connection.execute(
                """
                SELECT username, password_hash, created_at, updated_at
                FROM admins
                WHERE username = ?
                """,
                (username,),
            ).fetchone()
        return AdminAccount.model_validate(dict(row)) if row else None

    def create_admin_if_absent(self, username: str, password_hash: str) -> bool:
        """仅在没有任何管理员时创建账号，返回是否创建成功。"""
        timestamp = _utc_now_iso()
        with self._write_lock, self._connect() as connection:
            cursor = connection.execute(
                """
                INSERT INTO admins (username, password_hash, created_at, updated_at)
                SELECT ?, ?, ?, ?
                WHERE NOT EXISTS (SELECT 1 FROM admins)
                """,
                (username, password_hash, timestamp, timestamp),
            )
        return cursor.rowcount == 1

    def update_admin_password(self, username: str, password_hash: str) -> bool:
        """重设指定管理员的密码哈希，返回是否命中了账号。"""
        with self._write_lock, self._connect() as connection:
            cursor = connection.execute(
                "UPDATE admins SET password_hash = ?, updated_at = ? WHERE username = ?",
                (password_hash, _utc_now_iso(), username),
            )
        return cursor.rowcount == 1

    def delete_admin(self, username: str | None = None) -> int:
        """删除管理员账号；不传用户名时清空，用于忘记账号密码时的重置。"""
        with self._write_lock, self._connect() as connection:
            if username is None:
                cursor = connection.execute("DELETE FROM admins")
            else:
                cursor = connection.execute("DELETE FROM admins WHERE username = ?", (username,))
        return cursor.rowcount

    def list_wecom_apps(self) -> list[WeComApp]:
        """按 agentid 顺序返回已发现的自建应用。"""
        with self._connect() as connection:
            rows = connection.execute(
                """
                SELECT agent_id, name, console_app_id, last_synced_ip, last_synced_at,
                       current_trusted_ips, trusted_ip_checked_at, last_error
                FROM wecom_apps
                ORDER BY agent_id
                """
            ).fetchall()
        return [WeComApp.model_validate(_load_app_row(row)) for row in rows]

    def replace_wecom_apps(self, apps: list[WeComApp]) -> None:
        """用最新发现结果替换应用清单，同时保留已记录的同步状态。"""
        with self._write_lock, self._connect() as connection:
            connection.execute("DELETE FROM wecom_apps")
            connection.executemany(
                """
                INSERT INTO wecom_apps (
                    agent_id, name, console_app_id, last_synced_ip, last_synced_at,
                    current_trusted_ips, trusted_ip_checked_at, last_error
                )
                VALUES (
                    :agent_id, :name, :console_app_id, :last_synced_ip, :last_synced_at,
                    :current_trusted_ips, :trusted_ip_checked_at, :last_error
                )
                """,
                [self._dump_row(app) for app in apps],
            )

    def update_app_sync_result(
        self,
        agent_id: str,
        *,
        synced_ip: str | None,
        synced_at: str | None,
        error: str | None,
    ) -> None:
        """记录单个应用最近一次同步的 IP 或错误信息。"""
        with self._write_lock, self._connect() as connection:
            connection.execute(
                """
                UPDATE wecom_apps
                SET last_synced_ip = ?, last_synced_at = ?, last_error = ?
                WHERE agent_id = ?
                """,
                (synced_ip, synced_at, error, agent_id),
            )

    def update_app_console_id(self, agent_id: str, console_app_id: str | None) -> None:
        """补录某个应用在管理后台里的应用编号（与 agentid 不是同一个值）。"""
        with self._write_lock, self._connect() as connection:
            connection.execute(
                "UPDATE wecom_apps SET console_app_id = ? WHERE agent_id = ?",
                (console_app_id, agent_id),
            )

    def update_app_error(self, agent_id: str, error: str | None) -> None:
        """只更新某个应用的最近错误，保留覆盖记录与可信 IP 读数。"""
        with self._write_lock, self._connect() as connection:
            connection.execute(
                "UPDATE wecom_apps SET last_error = ? WHERE agent_id = ?",
                (error, agent_id),
            )

    def record_app_trusted_ips(
        self, agent_id: str, *, ips: list[str], checked_at: str
    ) -> None:
        """记录从企业微信读到的当前可信 IP 与读取时间。

        读到了就说明这次核对成功，顺带清掉上一次留下的错误。
        """
        with self._write_lock, self._connect() as connection:
            connection.execute(
                """
                UPDATE wecom_apps
                SET current_trusted_ips = ?, trusted_ip_checked_at = ?, last_error = NULL
                WHERE agent_id = ?
                """,
                (json.dumps(ips, ensure_ascii=False), checked_at, agent_id),
            )

    def record_public_ip(self, observation: PublicIpObservation) -> None:
        """追加一条公网 IP 观测记录。"""
        with self._write_lock, self._connect() as connection:
            connection.execute(
                """
                INSERT INTO public_ip_observations (ip, source, checked_at)
                VALUES (?, ?, ?)
                """,
                (observation.ip, observation.source, observation.checked_at.isoformat()),
            )

    def latest_public_ip(self) -> PublicIpObservation | None:
        """返回最近一次公网 IP 观测。"""
        with self._connect() as connection:
            row = connection.execute(
                """
                SELECT ip, source, checked_at
                FROM public_ip_observations
                ORDER BY id DESC
                LIMIT 1
                """
            ).fetchone()
        return PublicIpObservation.model_validate(dict(row)) if row else None

    def record_sync_summary(self, summary: SyncSummary) -> None:
        """追加一条同步历史。"""
        with self._write_lock, self._connect() as connection:
            connection.execute(
                """
                INSERT INTO sync_events (started_at, finished_at, public_ip, status, message, results)
                VALUES (?, ?, ?, ?, ?, ?)
                """,
                (
                    summary.started_at.isoformat(),
                    summary.finished_at.isoformat(),
                    summary.public_ip,
                    summary.status,
                    summary.message,
                    json.dumps([result.model_dump() for result in summary.results], ensure_ascii=False),
                ),
            )

    def list_sync_summaries(self, limit: int = 50) -> list[SyncSummary]:
        """按时间倒序返回同步历史。"""
        with self._connect() as connection:
            rows = connection.execute(
                """
                SELECT started_at, finished_at, public_ip, status, message, results
                FROM sync_events
                ORDER BY id DESC
                LIMIT ?
                """,
                (limit,),
            ).fetchall()
        summaries = []
        for row in rows:
            payload = dict(row)
            payload["results"] = json.loads(payload["results"])
            summaries.append(SyncSummary.model_validate(payload))
        return summaries

    def _get_json(self, key: str) -> dict | None:
        with self._connect() as connection:
            row = connection.execute("SELECT value FROM settings WHERE key = ?", (key,)).fetchone()
        return json.loads(row["value"]) if row else None

    def _set_json(self, key: str, value: dict) -> None:
        with self._write_lock, self._connect() as connection:
            connection.execute(
                """
                INSERT INTO settings (key, value) VALUES (?, ?)
                ON CONFLICT(key) DO UPDATE SET value = excluded.value
                """,
                (key, json.dumps(value, ensure_ascii=False)),
            )

    @staticmethod
    def _dump_row(app: WeComApp) -> dict:
        return {
            "agent_id": app.agent_id,
            "name": app.name,
            "console_app_id": app.console_app_id,
            "last_synced_ip": app.last_synced_ip,
            "last_synced_at": app.last_synced_at.isoformat() if app.last_synced_at else None,
            "current_trusted_ips": (
                None
                if app.current_trusted_ips is None
                else json.dumps(app.current_trusted_ips, ensure_ascii=False)
            ),
            "trusted_ip_checked_at": (
                app.trusted_ip_checked_at.isoformat() if app.trusted_ip_checked_at else None
            ),
            "last_error": app.last_error,
        }

    @contextmanager
    def _connect(self) -> Iterator[sqlite3.Connection]:
        connection = sqlite3.connect(self._database_path, timeout=5)
        connection.row_factory = sqlite3.Row
        connection.execute("PRAGMA journal_mode=WAL")
        try:
            yield connection
            connection.commit()
        finally:
            connection.close()


def _migrate_schema(connection: sqlite3.Connection) -> None:
    """补齐旧版本数据库缺失的列，保持升级后无需手工改库。"""
    columns = {row["name"] for row in connection.execute("PRAGMA table_info(wecom_apps)")}
    added_columns = {
        "console_app_id": "TEXT",
        "current_trusted_ips": "TEXT",
        "trusted_ip_checked_at": "TEXT",
    }
    for column, column_type in added_columns.items():
        if column not in columns:
            connection.execute(f"ALTER TABLE wecom_apps ADD COLUMN {column} {column_type}")


def _load_app_row(row: sqlite3.Row) -> dict:
    """把数据行转成模型输入，顺带还原以 JSON 存储的可信 IP 列表。"""
    payload = dict(row)
    stored_ips = payload.get("current_trusted_ips")
    if isinstance(stored_ips, str):
        try:
            restored = json.loads(stored_ips)
        except ValueError:
            restored = None
        payload["current_trusted_ips"] = restored if isinstance(restored, list) else None
    return payload


def _utc_now_iso() -> str:
    return datetime.now(timezone.utc).isoformat()
