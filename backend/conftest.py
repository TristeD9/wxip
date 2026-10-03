"""测试环境准备。

pytest 自带的 tmp_path 会调用 chmod，部分受限环境（Windows 沙箱、只读挂载）
会直接报 WinError 5。这里改装一个行为等价的临时目录 fixture，只做 mkdir。
"""

import shutil
import uuid
from pathlib import Path

import pytest

TEST_TEMP_DIR = Path(__file__).resolve().parent / ".pytest-tmp"
TEST_TEMP_DIR.mkdir(parents=True, exist_ok=True)


@pytest.fixture
def tmp_path():
    """在项目目录内创建一次性临时目录，避免系统 TEMP 的权限限制。"""
    case_dir = TEST_TEMP_DIR / f"case-{uuid.uuid4().hex[:10]}"
    case_dir.mkdir(parents=True, exist_ok=True)
    try:
        yield case_dir
    finally:
        shutil.rmtree(case_dir, ignore_errors=True)
