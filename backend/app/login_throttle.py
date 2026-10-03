"""登录失败节流：同一账号连续失败多次后临时锁定。"""

from __future__ import annotations

import threading
import time

MAX_FAILURES = 5
LOCKOUT_SECONDS = 300


class LoginThrottle:
    """按用户名记录失败次数，锁定到期后自动放行。"""

    def __init__(
        self, *, max_failures: int = MAX_FAILURES, lockout_seconds: int = LOCKOUT_SECONDS
    ) -> None:
        self._max_failures = max_failures
        self._lockout_seconds = lockout_seconds
        self._failures: dict[str, list[float]] = {}
        self._lock = threading.Lock()

    def locked_seconds_left(self, username: str, *, now: float | None = None) -> int:
        """返回剩余锁定秒数，未锁定时返回 0。"""
        current = now if now is not None else time.time()
        with self._lock:
            failures = self._recent_failures(username, current)
        if len(failures) < self._max_failures:
            return 0
        remaining = self._lockout_seconds - (current - failures[-1])
        return max(0, int(remaining))

    def record_failure(self, username: str, *, now: float | None = None) -> None:
        """记录一次登录失败。"""
        current = now if now is not None else time.time()
        with self._lock:
            failures = self._recent_failures(username, current)
            failures.append(current)
            self._failures[username] = failures

    def reset(self, username: str) -> None:
        """登录成功后清空失败记录。"""
        with self._lock:
            self._failures.pop(username, None)

    def _recent_failures(self, username: str, now: float) -> list[float]:
        failures = [
            moment
            for moment in self._failures.get(username, [])
            if now - moment < self._lockout_seconds
        ]
        self._failures[username] = failures
        return failures
