"""运维命令行：查看管理员、重设密码、忘记账号时的重置入口。

用法（在 backend 目录下执行）::

    python -m app.cli list-admins
    python -m app.cli set-password --username admin
    python -m app.cli reset-admin
    python -m app.cli check-trusted-ips
"""

from __future__ import annotations

import argparse
import asyncio
import getpass
import sys

from app.config import Settings
from app.passwords import check_password_strength, hash_password
from app.storage import AppStorage
from app.wecom.admin_browser import WeComAdminError, WeComAdminSession


def build_parser() -> argparse.ArgumentParser:
    """构造命令行解析器。"""
    parser = argparse.ArgumentParser(
        prog="python -m app.cli", description="企业微信可信 IP 维护服务运维命令"
    )
    subparsers = parser.add_subparsers(dest="command", required=True)
    subparsers.add_parser("list-admins", help="列出管理员用户名")

    set_password = subparsers.add_parser("set-password", help="重设管理员密码")
    set_password.add_argument("--username", required=True, help="管理员用户名")
    set_password.add_argument("--password", default=None, help="新密码；省略时交互式输入")

    reset_admin = subparsers.add_parser(
        "reset-admin", help="删除管理员账号，下次打开面板重新创建"
    )
    reset_admin.add_argument("--username", default=None, help="只删除指定用户；省略时全部删除")

    subparsers.add_parser(
        "check-trusted-ips", help="只读读取各应用当前可信 IP，逐条打印结果用于排查"
    )
    return parser


def main(argv: list[str] | None = None, settings: Settings | None = None) -> int:
    """执行运维命令，返回进程退出码。"""
    args = build_parser().parse_args(argv)
    app_settings = settings or Settings()
    app_settings.ensure_directories()
    storage = AppStorage(app_settings.database_path)
    storage.initialize()

    if args.command == "list-admins":
        return _list_admins(storage)
    if args.command == "set-password":
        return _set_password(storage, args.username, args.password)
    if args.command == "reset-admin":
        return _reset_admin(storage, args.username)
    if args.command == "check-trusted-ips":
        return _check_trusted_ips(app_settings, storage)
    return 1


def _list_admins(storage: AppStorage) -> int:
    usernames = storage.list_admin_usernames()
    if not usernames:
        print("当前没有管理员账号，打开面板即可重新创建。")
        return 0
    print("管理员账号：")
    for username in usernames:
        print(f"  - {username}")
    return 0


def _set_password(storage: AppStorage, username: str, password: str | None) -> int:
    if storage.get_admin(username) is None:
        print(f"管理员 {username} 不存在，可先执行 list-admins 查看现有账号。")
        return 1
    new_password = password or getpass.getpass("请输入新密码：")
    problem = check_password_strength(new_password)
    if problem:
        print(problem)
        return 1
    storage.update_admin_password(username, hash_password(new_password))
    print(f"已更新管理员 {username} 的密码。")
    return 0


def _reset_admin(storage: AppStorage, username: str | None) -> int:
    removed = storage.delete_admin(username)
    if removed == 0:
        print("没有删除任何账号，请用 list-admins 确认现有用户名。")
        return 1
    if username:
        print(f"已删除管理员 {username}。")
    else:
        print("已清空全部管理员账号。")
    print("下次打开面板会进入「创建管理员账号」页面。")
    return 0


def _check_trusted_ips(settings: Settings, storage: AppStorage) -> int:
    """只读复现一次"读取当前可信 IP"，把结果打到终端，便于排查读取失败。"""
    return asyncio.run(_check_trusted_ips_async(settings, storage))


async def _check_trusted_ips_async(settings: Settings, storage: AppStorage) -> int:
    apps = storage.list_wecom_apps()
    print(f"应用清单：{len(apps)} 个")
    print(f"写入模板：{'已配置' if storage.get_request_template() else '未配置'}")
    print(f"备用读取模板：{'已配置' if storage.get_read_template() else '未配置（不影响读取）'}")
    if not apps:
        print("没有应用清单，请先到面板「企业微信」页自动发现或手工导入。")
        return 1

    session = WeComAdminSession(
        state_path=settings.wecom_state_path,
        headless=settings.browser_headless,
        channel=settings.browser_channel,
        timeout_ms=settings.browser_timeout_ms,
        apps_url_provider=storage.get_wecom_apps_url,
    )
    try:
        trusted_ips_by_agent = await session.read_app_trusted_ips()
    except WeComAdminError as error:
        print(f"读取失败：{error}")
        return 1
    finally:
        await session.close()

    missing = 0
    for app in apps:
        if app.agent_id not in trusted_ips_by_agent:
            missing += 1
            print(f"[{app.agent_id}] {app.name}：未读到（控制台编号 {app.console_app_id or '未填'}）")
            continue
        trusted_ips = trusted_ips_by_agent[app.agent_id]
        print(f"[{app.agent_id}] {app.name}：当前可信 IP = {'、'.join(trusted_ips) or '（空）'}")
    print(f"\n完成：{len(apps) - missing}/{len(apps)} 个应用读到当前可信 IP。")
    return 0 if missing == 0 else 1


if __name__ == "__main__":
    sys.exit(main())
