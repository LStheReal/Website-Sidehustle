#!/usr/bin/env python3
"""
Retry decorator with exponential backoff for transient failures.

Usage:
    from execution.retry_utils import retry_with_backoff

    @retry_with_backoff(max_attempts=3, initial_delay=2.0)
    def flaky_call():
        ...

    @retry_with_backoff(max_attempts=3, initial_delay=5.0, exceptions=(requests.RequestException,))
    def http_call():
        ...
"""

import functools
import time


def retry_with_backoff(
    max_attempts: int = 3,
    initial_delay: float = 2.0,
    backoff: float = 2.0,
    exceptions: tuple = (Exception,),
    on_retry=None,
):
    """
    Decorator that retries a function on exception with exponential backoff.

    Args:
        max_attempts: Total attempts (including the first one). Must be >= 1.
        initial_delay: Seconds to wait before the first retry.
        backoff: Multiplier applied to the delay after each failed attempt.
        exceptions: Tuple of exception classes that should trigger a retry.
                    Any other exception type bubbles up immediately.
        on_retry: Optional callable(attempt, exc, delay) invoked before each
                  sleep. Useful for logging.

    Returns:
        Wrapped function that retries up to `max_attempts` times before
        re-raising the final exception.
    """
    if max_attempts < 1:
        raise ValueError("max_attempts must be >= 1")

    def decorator(fn):
        @functools.wraps(fn)
        def wrapper(*args, **kwargs):
            delay = initial_delay
            last_exc = None
            for attempt in range(1, max_attempts + 1):
                try:
                    return fn(*args, **kwargs)
                except exceptions as exc:
                    last_exc = exc
                    if attempt == max_attempts:
                        raise
                    if on_retry is not None:
                        try:
                            on_retry(attempt, exc, delay)
                        except Exception:
                            pass
                    else:
                        print(
                            f"[retry] {fn.__name__} attempt {attempt}/{max_attempts} "
                            f"failed: {exc!r}. Sleeping {delay:.1f}s.",
                            flush=True,
                        )
                    time.sleep(delay)
                    delay *= backoff
            # Should be unreachable, but keep for type-checkers.
            raise last_exc  # type: ignore[misc]

        return wrapper

    return decorator
