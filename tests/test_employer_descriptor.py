"""Э4.1 dual_employment_and_contracting_2026.md: дескриптор работодателя (`employer_descriptor.py`)."""

from __future__ import annotations

from typing import Any

from core.domains.profile.employer_descriptor import (
    EmployerDescriptor,
    get_or_create_employer_descriptor,
    load_descriptor,
)
from core.kernel.errors import LlmError
from tests.fakes import FakeLlm, RaisingLlm


class FakeDescriptorDb:
    """Двойник Executor для таблицы `employer_descriptors` (in-memory)."""

    def __init__(self) -> None:
        self._rows: dict[tuple[int, str], dict[str, Any]] = {}

    async def fetchrow(self, query: str, *args: Any) -> dict[str, Any] | None:
        if "select descriptor from employer_descriptors" in query:
            account_id, canonical = args
            row = self._rows.get((account_id, canonical))
            return {"descriptor": row} if row is not None else None
        raise NotImplementedError(query)

    async def execute(self, query: str, *args: Any) -> None:
        if "insert into employer_descriptors" in query:
            account_id, canonical, descriptor = args
            self._rows[(account_id, canonical)] = descriptor
            return
        raise NotImplementedError(query)


def _clean_descriptor() -> EmployerDescriptor:
    return EmployerDescriptor(
        descriptor_ru="крупный облачный провайдер",
        descriptor_en="a major cloud provider",
        industry="IT",
    )


async def test_empty_company_returns_none() -> None:
    db = FakeDescriptorDb()
    result = await get_or_create_employer_descriptor(1, company="", db=db, llm=FakeLlm())
    assert result is None


async def test_creates_and_caches_descriptor() -> None:
    db = FakeDescriptorDb()
    llm = FakeLlm(result=_clean_descriptor())
    result = await get_or_create_employer_descriptor(
        1, company="Acme Inc", industry="IT", db=db, llm=llm
    )
    assert result is not None
    assert result.descriptor_ru == "крупный облачный провайдер"
    assert len(llm.calls) == 1

    # Второй вызов на ту же компанию - из кэша, LLM не дёргается.
    cached = await get_or_create_employer_descriptor(1, company="Acme Inc", db=db, llm=RaisingLlm())
    assert cached == result


async def test_load_descriptor_reads_cache_without_llm() -> None:
    db = FakeDescriptorDb()
    llm = FakeLlm(result=_clean_descriptor())
    await get_or_create_employer_descriptor(1, company="Acme Inc", db=db, llm=llm)

    from core.domains.opportunities.companies.normalize import normalize_company_deterministic

    canonical = normalize_company_deterministic("Acme Inc")
    cached = await load_descriptor(1, canonical, db=db)
    assert cached is not None
    assert cached.descriptor_en == "a major cloud provider"


async def test_leaked_company_name_retries_then_falls_back() -> None:
    """Дескриптор с именем компании внутри - гвард отбрасывает, ремонт ≤1, затем фолбэк (§2.8)."""
    db = FakeDescriptorDb()
    leaking = EmployerDescriptor(descriptor_ru="Acme Inc - облачный провайдер", descriptor_en="ok")
    llm = FakeLlm(results=[leaking, leaking])  # оба вызова "текут" -> ни один не проходит гвард
    result = await get_or_create_employer_descriptor(
        1, company="Acme Inc", industry="IT", db=db, llm=llm
    )
    assert result is not None
    assert "acme" not in result.descriptor_ru.lower()
    assert "acme" not in result.descriptor_en.lower()
    assert len(llm.calls) == 2  # ровно один повтор (L-13), не бесконечный цикл


async def test_llm_error_falls_back_without_raising() -> None:
    db = FakeDescriptorDb()
    llm = FakeLlm(error=LlmError("нет ключа"))
    result = await get_or_create_employer_descriptor(1, company="Acme Inc", db=db, llm=llm)
    assert result is not None
    assert result.descriptor_ru == "текущее место работы"
