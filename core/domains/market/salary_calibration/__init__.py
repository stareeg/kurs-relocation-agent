"""Калибровка зарплат: префильтр постов, LLM-извлечение вилок, агрегация и бенчмарки.

LLM-путь — через порт `kernel.ports.llm().complete`; персистентная модель —
`core.domains.market.salary_calib.CalibSample`.
"""

from core.domains.market.salary_calibration.salary_aggregate import (
    MIN_SEGMENT_SAMPLES,
    SalaryPrior,
    build_calibration_report,
    compute_segment_prior,
    dedupe_samples,
    filter_outliers,
)
from core.domains.market.salary_calibration.salary_benchmark_sync import (
    build_benchmark_insights,
    export_calibration_snapshot,
)
from core.domains.market.salary_calibration.salary_extract import extract_salary_batch
from core.domains.market.salary_calibration.salary_prefilter import (
    looks_like_salary_post,
    looks_like_vacancy_post,
)

__all__ = [
    "looks_like_salary_post",
    "looks_like_vacancy_post",
    "extract_salary_batch",
    "build_calibration_report",
    "compute_segment_prior",
    "dedupe_samples",
    "filter_outliers",
    "SalaryPrior",
    "MIN_SEGMENT_SAMPLES",
    "build_benchmark_insights",
    "export_calibration_snapshot",
]
