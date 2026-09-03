"""Общий HTTP-транспорт platform (L-07…L-09): keep-alive, прогрев, retry-политика."""

from core.platform.http.client import (
    close_http_client,
    get_http_client,
    init_http_client,
    make_client,
    request_timeout,
    warmup_openrouter,
)
from core.platform.http.retry import (
    backoff_with_jitter,
    can_retry_within_budget,
    is_retryable_http_status,
    plan_retry,
)

__all__ = [
    "backoff_with_jitter",
    "can_retry_within_budget",
    "close_http_client",
    "get_http_client",
    "init_http_client",
    "is_retryable_http_status",
    "make_client",
    "plan_retry",
    "request_timeout",
    "warmup_openrouter",
]
