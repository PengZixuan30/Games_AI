"""Wait for a condition instead of sleeping a fixed time and hoping.

The cross-server suites spend most of their wall clock waiting for a peer to register, for a link
to drop or for a reconnect to land. A fixed ``time.sleep`` makes those tests both slow and flaky;
:func:`wait_until` polls instead and hands the last value back to the caller, which then asserts on
it -- so a failure message still carries the state that never became true.
"""
import time


def wait_until(predicate, timeout: float = 10.0, interval: float = 0.05):
    """Call ``predicate`` until it returns something truthy, or ``timeout`` seconds pass.

    Returns the last value ``predicate`` produced: a falsy value means it never became true, and
    the caller asserts on it (``assert wait_until(..., 20), hub.peers``).
    """
    deadline = time.monotonic() + timeout
    value = predicate()
    while not value and time.monotonic() < deadline:
        time.sleep(interval)
        value = predicate()
    return value
