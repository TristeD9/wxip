"""登录失败节流。"""

from app.login_throttle import LoginThrottle


def test_not_locked_before_threshold():
    throttle = LoginThrottle(max_failures=3, lockout_seconds=300)

    throttle.record_failure("admin", now=1_000)
    throttle.record_failure("admin", now=1_001)

    assert throttle.locked_seconds_left("admin", now=1_002) == 0


def test_locked_after_threshold():
    throttle = LoginThrottle(max_failures=3, lockout_seconds=300)
    for moment in (1_000, 1_001, 1_002):
        throttle.record_failure("admin", now=moment)

    assert throttle.locked_seconds_left("admin", now=1_003) == 299


def test_lock_expires_after_lockout_window():
    throttle = LoginThrottle(max_failures=2, lockout_seconds=300)
    throttle.record_failure("admin", now=1_000)
    throttle.record_failure("admin", now=1_010)

    assert throttle.locked_seconds_left("admin", now=1_400) == 0


def test_reset_clears_failures():
    throttle = LoginThrottle(max_failures=2, lockout_seconds=300)
    throttle.record_failure("admin", now=1_000)

    throttle.reset("admin")

    assert throttle.locked_seconds_left("admin", now=1_001) == 0


def test_failures_are_tracked_per_username():
    throttle = LoginThrottle(max_failures=2, lockout_seconds=300)
    throttle.record_failure("admin", now=1_000)
    throttle.record_failure("admin", now=1_001)

    assert throttle.locked_seconds_left("someone-else", now=1_002) == 0
