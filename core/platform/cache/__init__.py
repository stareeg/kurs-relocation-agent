"""Кэш платформы: single-flight и кэш результатов LLM."""

from core.platform.cache.result_cache import (
    DEFAULT_TTL_S,
    LayeredResultCache,
    MemoryResultCache,
    PostgresResultCache,
    ResultCache,
    get_result_cache,
    reset_result_cache_for_tests,
    set_result_cache_for_tests,
)
from core.platform.cache.single_flight import (
    SingleFlight,
    get_single_flight,
    reset_single_flight_for_tests,
    set_single_flight_for_tests,
)

__all__ = [
    "DEFAULT_TTL_S",
    "LayeredResultCache",
    "MemoryResultCache",
    "PostgresResultCache",
    "ResultCache",
    "SingleFlight",
    "get_result_cache",
    "get_single_flight",
    "reset_result_cache_for_tests",
    "reset_single_flight_for_tests",
    "set_result_cache_for_tests",
    "set_single_flight_for_tests",
]
