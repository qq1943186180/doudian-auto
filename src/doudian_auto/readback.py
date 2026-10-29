"""Bounded read-only observations after a single save attempt."""

import time


def wait_for_target_titles(read_pair, target_title, *, seconds=30, max_attempts=3):
    """Allow delayed propagation; never resubmit or interpret an old title as failure.

    Each probe must return newly fetched Miaoshou and official Doudian snapshots.
    This function only waits for target titles; full image/protected-field checks
    remain the caller's responsibility. New probes stop at the shared deadline.
    """
    deadline = time.monotonic() + min(30, max(0, seconds))
    pair = None
    for attempt in range(max(1, min(3, max_attempts))):
        if attempt and time.monotonic() >= deadline:
            break
        pair = read_pair()
        if all(page.get('title') == target_title for page in pair):
            return pair
        if attempt + 1 < max_attempts:
            time.sleep(min(1, max(0, deadline - time.monotonic())))
    return pair
