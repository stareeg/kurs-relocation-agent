"""Этап 8 §8.1: дедуп проверяется ДО скоринга в `score_and_persist`.

До фикса единственная проверка кросс-площадочного дубля жила в `persist_scored_with_repo` —
уже после того, как `score_and_persist` заплатил LLM-вызовом за вакансию, чей текст уже лежит
в базе под другим `vacancy_id`. Здесь проверяем: если у канона уже есть валидный скор,
`score_vacancy` не зовётся вовсе; если скора у канона нет (стаб) — скорим как обычно, и
пост-скоринговый дедуп в `persist_scored_with_repo` всё равно приклеит ссылку к канону.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any

import pytest

from core.domains.opportunities import persist
from core.domains.opportunities.jobs import ApplicationStage, Job, JobLink
from core.domains.opportunities.models import (
    BurnoutRisk,
    GradeMatch,
    RemoteAbroadCompat,
    RoleContentMatch,
    SalaryInfo,
    ScoreResult,
    VacancyInput,
)
from core.kernel import ports

# Почти один в один: Jaccard > 0.9 (см. test_dedup_persist.py).
_CANONICAL_TEXT = (
    "Senior Python Developer. "
    "Мы ищем опытного разработчика в команду высоконагруженных сервисов. "
    "Требуется Docker Kubernetes PostgreSQL опыт коммерческой разработки от 5 лет. "
    "Удалённая работа гибкий график ДМС зарплата 350 000 до 500 000 рублей в месяц. "
    "Яндекс продуктовая разработка Москва."
)
_DUP_TEXT = (
    "Senior Python разработчик. "
    "Мы ищем опытного разработчика в команду высоконагруженных сервисов. "
    "Требуется Docker Kubernetes PostgreSQL опыт коммерческой разработки от 5 лет. "
    "Удалённая работа гибкий график ДМС зарплата 350 000 до 500 000 рублей в месяц. "
    "Яндекс продуктовая разработка москва."
)


def _sample_score(overall_score: int = 85) -> ScoreResult:
    return ScoreResult(
        overall_score=overall_score,
        recommendation="apply",
        remote_abroad_compat=RemoteAbroadCompat(level="ok", reasoning="r"),
        grade_match=GradeMatch(level="match", reasoning="r"),
        salary=SalaryInfo(meets_min=True, value_or_range="350 000–500 000 ₽", note=""),
        role_content_match=RoleContentMatch(score=70, matched_niche=[], reasoning="r"),
        burnout_risk=BurnoutRisk(level="low", reasoning="r"),
        company_type="product",
        pros=["p"],
        cons=["c"],
        red_flags=[],
        one_line_verdict="v",
    )


@dataclass
class _MemJobsDedup:
    """Тот же memory-репозиторий, что в test_dedup_persist.py (независимая копия — не импортируем
    тестовый модуль из тестового модуля)."""

    jobs: dict[str, Job] = field(default_factory=dict)
    links: list[JobLink] = field(default_factory=list)
    stages: list[ApplicationStage] = field(default_factory=list)
    _seq: int = 0

    def _next_id(self) -> int:
        self._seq += 1
        return self._seq

    async def save(self, job: Job, *, preserve_status: bool = False) -> Job:
        _ = preserve_status
        job_id = job.id or self._next_id()
        saved = job.model_copy(update={"id": job_id})
        key = saved.vacancy_id or str(job_id)
        self.jobs[key] = saved
        return saved

    async def add_stage(
        self, job_id: int, stage: str, *, source: str = "manual", applied_at: str | None = None
    ) -> ApplicationStage:
        _ = applied_at
        st = ApplicationStage(id=self._next_id(), job_id=job_id, stage=stage, source=source)
        self.stages.append(st)
        return st

    async def get_by_vacancy_id(self, vacancy_id: str) -> Job | None:
        return self.jobs.get(vacancy_id)

    async def find_duplicate_candidates(self, tokens: list[str], *, limit: int = 20) -> list[Job]:
        return [j for j in self.jobs.values() if j.vacancy_text.strip()]

    async def add_job_link(
        self,
        job_id: int,
        *,
        source: str,
        vacancy_id: str | None,
        url: str | None,
        is_primary: bool = False,
    ) -> JobLink:
        link = JobLink(
            id=self._next_id(),
            job_id=job_id,
            source=source,
            vacancy_id=vacancy_id,
            url=url,
            is_primary=is_primary,
        )
        self.links.append(link)
        return link

    async def enrich_job(
        self,
        job_id: int,
        *,
        salary_text: str | None = None,
        title: str | None = None,
        company: str | None = None,
        work_format: str | None = None,
        published_at: str | None = None,
        url: str | None = None,
        vacancy_text: str | None = None,
    ) -> Job | None:
        for key, j in self.jobs.items():
            if j.id == job_id:
                updates: dict[str, Any] = {}
                if not j.title and title:
                    updates["title"] = title
                if not j.url and url:
                    updates["url"] = url
                updated = j.model_copy(update=updates)
                self.jobs[key] = updated
                return updated
        return None


def _canonical_job(*, score: dict[str, Any]) -> Job:
    return Job(
        id=1,
        vacancy_id="12345",
        source="vacancy_page",
        title="Senior Python Developer",
        company="Яндекс",
        vacancy_text=_CANONICAL_TEXT,
        url="https://hh.ru/vacancy/12345",
        status="Просмотр",
        overall_score=score.get("overall_score"),
        recommendation=score.get("recommendation"),
        score=score,
    )


@pytest.fixture(autouse=True)
def _clean_ports():
    ports.reset()
    yield
    ports.reset()


@pytest.fixture(autouse=True)
def _no_follow_ups(monkeypatch: pytest.MonkeyPatch) -> None:
    # Фоновые LLM-догонки (вилка/причины пропуска) — вне периметра этого теста.
    monkeypatch.setattr(persist, "schedule_post_persist_follow_ups", lambda *a, **k: None)
    monkeypatch.setattr(persist, "learned_preferences_block_safe", _empty_preferences)

    async def _fake_remote(_text: str) -> None:
        return None

    monkeypatch.setattr(persist, "assess_remote_feasibility_safe", _fake_remote)


async def _empty_preferences(_account_id: int, **_kwargs: Any) -> str:
    return ""


async def test_duplicate_with_scored_canonical_skips_llm_call(monkeypatch: pytest.MonkeyPatch):
    """Канон уже оценён — `score_vacancy` не зовётся вовсе, скор берётся из канона."""
    repo = _MemJobsDedup()
    canonical = _canonical_job(score=_sample_score(overall_score=91).model_dump(mode="json"))
    repo.jobs["12345"] = canonical

    monkeypatch.setattr(persist, "PgJobsRepository", lambda *_a, **_kw: repo)

    async def _forbidden_score_vacancy(*_a: Any, **_kw: Any) -> ScoreResult:
        raise AssertionError("score_vacancy не должен звонить LLM для уже оценённого дубля")

    monkeypatch.setattr(persist, "score_vacancy", _forbidden_score_vacancy)

    vac = VacancyInput(
        source="habr",
        vacancy_id="habr_100",
        text=_DUP_TEXT,
        title="Senior Python Developer",
        url="https://career.habr.com/vacancies/100",
    )

    result = await persist.score_and_persist(vac, account_id=1, db=object())

    assert result.job.id == 1
    assert result.job.vacancy_id == "12345"
    assert result.score.overall_score == 91
    assert len(repo.links) == 1
    assert repo.links[0].vacancy_id == "habr_100"
    # Новой записи jobs не заведено.
    assert len(repo.jobs) == 1


async def test_duplicate_with_unscored_canonical_scores_normally(monkeypatch: pytest.MonkeyPatch):
    """Канон-стаб без валидного score (пустой jsonb) — LLM зовётся как обычно, пост-скоринговый
    дедуп в `persist_scored_with_repo` всё равно склеивает с каноном."""
    repo = _MemJobsDedup()
    canonical = _canonical_job(score={})
    repo.jobs["12345"] = canonical

    monkeypatch.setattr(persist, "PgJobsRepository", lambda *_a, **_kw: repo)

    calls = {"n": 0}

    async def _score_vacancy(*_a: Any, **_kw: Any) -> ScoreResult:
        calls["n"] += 1
        return _sample_score(overall_score=77)

    monkeypatch.setattr(persist, "score_vacancy", _score_vacancy)

    vac = VacancyInput(
        source="habr",
        vacancy_id="habr_101",
        text=_DUP_TEXT,
        title="Senior Python Developer",
        url="https://career.habr.com/vacancies/101",
    )

    result = await persist.score_and_persist(vac, account_id=1, db=object())

    assert calls["n"] == 1
    assert result.job.id == 1  # всё равно канон — пост-скоринговый дедуп нашёл тот же дубль
    assert result.score.overall_score == 77
    assert len(repo.links) == 1
    assert len(repo.jobs) == 1


async def test_no_duplicate_scores_and_persists_normally(monkeypatch: pytest.MonkeyPatch):
    """Нет дубля — обычный путь, ровно один вызов `score_vacancy`, новая запись jobs."""
    repo = _MemJobsDedup()
    repo.jobs["other"] = _canonical_job(score={}).model_copy(
        update={"vacancy_text": "совсем другой текст про Frontend React разработку"}
    )
    repo._seq = 1  # id=1 уже занят каноном выше — следующий save() не должен на него наткнуться

    monkeypatch.setattr(persist, "PgJobsRepository", lambda *_a, **_kw: repo)

    calls = {"n": 0}

    async def _score_vacancy(*_a: Any, **_kw: Any) -> ScoreResult:
        calls["n"] += 1
        return _sample_score(overall_score=60)

    monkeypatch.setattr(persist, "score_vacancy", _score_vacancy)

    vac = VacancyInput(
        source="habr",
        vacancy_id="habr_999",
        text=(
            "Абсолютно другой текст про Frontend React — "
            "не менее пятидесяти символов для валидации"
        ),
        title="Frontend Developer",
        url="https://career.habr.com/vacancies/999",
    )

    result = await persist.score_and_persist(vac, account_id=1, db=object())

    assert calls["n"] == 1
    assert result.job.vacancy_id == "habr_999"
    assert len(repo.links) == 0


async def test_no_vacancy_id_bypasses_pre_check_without_touching_repo(
    monkeypatch: pytest.MonkeyPatch,
):
    """Без vacancy_id дедуп-проверка не должна даже трогать репозиторий (нечего искать) —
    в частности, не должна открывать ``ports.uow()``, если ``db`` не передан."""

    async def _score_vacancy(*_a: Any, **_kw: Any) -> ScoreResult:
        return _sample_score()

    async def _fake_persist_scored(vac: VacancyInput, score: ScoreResult, **_kwargs: Any):
        job = Job(
            vacancy_id=vac.vacancy_id, vacancy_text=vac.text, overall_score=score.overall_score
        )
        return persist.ScoredJob(job=job, score=score)

    monkeypatch.setattr(persist, "score_vacancy", _score_vacancy)
    monkeypatch.setattr(persist, "persist_scored", _fake_persist_scored)

    # ports.uow() не связан (см. _clean_ports) — если код попытается его открыть, тест упадёт.
    result = await persist.score_and_persist(VacancyInput(text="x" * 60), account_id=1)

    assert result.score.overall_score == 85
