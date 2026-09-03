"""Канонизация названий компаний (FR2-39+)."""

from core.domains.opportunities.companies.normalize import (
    COMPANY_ALIASES,
    needs_brand_extract,
    normalize_company,
    normalize_company_deterministic,
)

__all__ = [
    "COMPANY_ALIASES",
    "needs_brand_extract",
    "normalize_company",
    "normalize_company_deterministic",
]
