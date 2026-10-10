"""运维命令行：查看管理员、重置账号与可信 IP 读取排查。"""

from __future__ import annotations

from app.cli import main
from app.config import Settings
from app.passwords import hash_password, verify_password
from app.storage import AppStorage


def build_storage(tmp_path) -> AppStorage:
    storage = AppStorage(tmp_path / "app.sqlite3")
    storage.initialize()
    return storage


def build_settings(tmp_path) -> Settings:
    return Settings(data_dir=tmp_path, secret_key="cli-test-secret")


def test_list_admins_reports_empty_state(tmp_path, capsys):
    exit_code = main(["list-admins"], settings=build_settings(tmp_path))

    assert exit_code == 0
    assert "没有管理员账号" in capsys.readouterr().out


def test_list_admins_prints_usernames(tmp_path, capsys):
    storage = build_storage(tmp_path)
    storage.create_admin_if_absent("admin", hash_password("admin-pass-123"))

    exit_code = main(["list-admins"], settings=build_settings(tmp_path))

    assert exit_code == 0
    assert "admin" in capsys.readouterr().out


def test_set_password_updates_hash(tmp_path):
    storage = build_storage(tmp_path)
    storage.create_admin_if_absent("admin", hash_password("old-pass-123"))

    exit_code = main(
        ["set-password", "--username", "admin", "--password", "new-pass-456"],
        settings=build_settings(tmp_path),
    )

    updated = build_storage(tmp_path).get_admin("admin")
    assert exit_code == 0
    assert updated is not None
    assert verify_password("new-pass-456", updated.password_hash) is True


def test_set_password_fails_for_unknown_user(tmp_path, capsys):
    exit_code = main(
        ["set-password", "--username", "ghost", "--password", "new-pass-456"],
        settings=build_settings(tmp_path),
    )

    assert exit_code == 1
    assert "不存在" in capsys.readouterr().out


def test_reset_admin_clears_accounts(tmp_path, capsys):
    storage = build_storage(tmp_path)
    storage.create_admin_if_absent("admin", hash_password("admin-pass-123"))

    exit_code = main(["reset-admin"], settings=build_settings(tmp_path))

    assert exit_code == 0
    assert build_storage(tmp_path).count_admins() == 0
    assert "创建管理员账号" in capsys.readouterr().out


def test_reset_admin_reports_when_nothing_to_delete(tmp_path, capsys):
    exit_code = main(["reset-admin"], settings=build_settings(tmp_path))

    assert exit_code == 1
    assert "没有删除任何账号" in capsys.readouterr().out


def test_check_trusted_ips_reports_missing_apps(tmp_path, capsys):
    exit_code = main(["check-trusted-ips"], settings=build_settings(tmp_path))

    assert exit_code == 1
    output = capsys.readouterr().out
    assert "应用清单：0 个" in output
    assert "没有应用清单" in output
