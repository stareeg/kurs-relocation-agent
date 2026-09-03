"""Тесты хука дедупликации в persist_scored_with_repo.

Проверяем: дубль не плодит новую запись jobs, а добавляет ссылку к канонической
и дозаполняет пустые поля. Проверяем через memory-репозиторий (без БД).
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any

import pytest

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
from core.domains.opportunities.persist import persist_scored_with_repo
from core.domains.opportunities.ports import JobsRepository
from core.kernel import ports


@dataclass
class _MemJobsDedup:
    """Memory JobsRepository с поддержкой дедупликации — для тестов persist_scored."""

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
        self,
        job_id: int,
        stage: str,
        *,
        source: str = "manual",
        applied_at: str | None = None,
    ) -> ApplicationStage:
        _ = applied_at
        st = ApplicationStage(id=self._next_id(), job_id=job_id, stage=stage, source=source)
        self.stages.append(st)
        found_key = next(
            (k for k, j in self.jobs.items() if j.id == job_id), None
        )
        if found_key:
            self.jobs[found_key] = self.jobs[found_key].model_copy(update={"status": stage})
        return st

    async def get_by_vacancy_id(self, vacancy_id: str) -> Job | None:
        return self.jobs.get(vacancy_id)

    async def find_duplicate_candidates(
        self, tokens: list[str], *, limit: int = 20
    ) -> list[Job]:
        # Для memory-теста: просто возвращаем все jobs с непустым текстом.
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
                if not j.salary_text and salary_text:
                    updates["salary_text"] = salary_text
                if not j.title and title:
                    updates["title"] = title
                if not j.company and company:
                    updates["company"] = company
                if not j.work_format and work_format:
                    updates["work_format"] = work_format
                if not j.published_at and published_at:
                    updates["published_at"] = published_at
                if not j.url and url:
                    updates["url"] = url
                if not j.vacancy_text.strip() and vacancy_text:
                    updates["vacancy_text"] = vacancy_text
                updated = j.model_copy(update=updates)
                self.jobs[key] = updated
                return updated
        return None


@pytest.fixture(autouse=True)
def _clean_ports():
    ports.reset()
    yield
    ports.reset()


# Каноническая вакансия hh и её дубль с Хабр — почти один в один: Jaccard > 0.9.
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


def _sample_score() -> ScoreResult:
    return ScoreResult(
        overall_score=85,
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


def _build_canonical(vacancy_id: str = "12345", title: str | None = "Senior Python Developer") -> Job:
    """Каноническая вакансия hh (уже проскорена и лежит в jobs)."""
    return Job(
        id=1,
        vacancy_id=vacancy_id,
        source="vacancy_page",
        title=title,
        company="Яндекс",
        vacancy_text=_CANONICAL_TEXT,
        salary_text="350 000–500 000 ₽",
        work_format="remote",
        url="https://hh.ru/vacancy/12345",
        status="Просмотр",
        overall_score=85,
        recommendation="apply",
        work_city="Москва",
        score={},
        salary=_sample_score().salary.model_dump(mode="json"),
    )


# --------------------------------------------------------------------------- тесты


async def test_no_duplicate_creates_new_job():
    """Если дубля нет — обычный персист (новая запись jobs)."""
    repo = _MemJobsDedup()
    repo.jobs["old"] = _build_canonical()  # нерелевантная вакансия

    vac = VacancyInput(
        source="habr",
        vacancy_id="habr_999",
        text="Абсолютно другой текст про Frontend React — не менее пятидесяти символов для валидации модели",
        title="Frontend Developer",
        url="https://career.habr.com/vacancies/999",
    )
    result = await persist_scored_with_repo(
        vac, _sample_score(), repo=repo, account_id=1
    )
    assert result.job.vacancy_id == "habr_999"
    # Новая запись jobs, а не ссылка к канону
    assert len(repo.links) == 0
    # Старая вакансия не тронута
    assert repo.jobs["old"].vacancy_id == "12345"


async def test_duplicate_adds_link_not_new_job():
    """Дубль не создаёт новый jobs — добавляет job_link к канонической."""
    repo = _MemJobsDedup()
    canonical = _build_canonical(title=None)  # title пустой — должен дозаполниться
    repo.jobs["12345"] = canonical

    vac = VacancyInput(
        source="habr",
        vacancy_id="habr_100",
        text=_DUP_TEXT,
        title="Senior Python Developer",
        url="https://career.habr.com/vacancies/100",
        salary_text="350 000–500 000 ₽",
        company="Яндекс",
        work_format="remote",
    )
    result = await persist_scored_with_repo(
        vac, _sample_score(), repo=repo, account_id=1
    )
    # Вернулась каноническая запись (не новая)
    assert result.job.id == 1
    assert result.job.vacancy_id == "12345"
    # Ссылка добавлена
    assert len(repo.links) == 1
    link = repo.links[0]
    assert link.job_id == 1
    assert link.source == "habr"
    assert link.vacancy_id == "habr_100"
    # Новых jobs не заведено
    assert len(repo.jobs) == 1
    assert "habr_100" not in repo.jobs


async def test_duplicate_enriches_empty_fields():
    """Дозаполнение пустых полей канонической вакансии."""
    repo = _MemJobsDedup()
    # Канон без title и без url
    canonical = _build_canonical(title=None)
    canonical = canonical.model_copy(update={"url": None})
    repo.jobs["12345"] = canonical

    vac = VacancyInput(
        source="habr",
        vacancy_id="habr_101",
        text=_DUP_TEXT,
        title="Senior Python Developer",
        url="https://career.habr.com/vacancies/101",
    )
    result = await persist_scored_with_repo(
        vac, _sample_score(), repo=repo, account_id=1
    )
    # Канон обогащён
    assert result.job.title == "Senior Python Developer"
    assert result.job.url == "https://career.habr.com/vacancies/101"


async def test_duplicate_does_not_overwrite_existing_fields():
    """Если поле у канона уже заполнено — не перезаписываем."""
    repo = _MemJobsDedup()
    canonical = _build_canonical(title="Original Title")
    canonical = canonical.model_copy(update={"url": "https://hh.ru/vacancy/12345"})
    repo.jobs["12345"] = canonical

    vac = VacancyInput(
        source="habr",
        vacancy_id="habr_102",
        text=_DUP_TEXT,
        title="Another Title",
        url="https://career.habr.com/vacancies/102",
    )
    result = await persist_scored_with_repo(
        vac, _sample_score(), repo=repo, account_id=1
    )
    assert result.job.title == "Original Title"
    assert result.job.url == "https://hh.ru/vacancy/12345"


async def test_existing_vacancy_by_id_bypasses_dedup():
    """Повторный скоринг той же вакансии (existing по vacancy_id) — без дубля."""
    repo = _MemJobsDedup()
    repo.jobs["habr_200"] = _build_canonical("habr_200")

    vac = VacancyInput(
        source="habr",
        vacancy_id="habr_200",
        text="какой-то текст вакансии достаточной длины чтобы пройти валидацию min_length 50 символов",
        title="LT",
    )
    result = await persist_scored_with_repo(
        vac, _sample_score(), repo=repo, account_id=1
    )
    assert result.job.vacancy_id == "habr_200"
    assert len(repo.links) == 0  # повторный upsert, не ссылка
    assert len(repo.jobs) == 1


async def test_no_vacancy_id_bypasses_dedup():
    """Без vacancy_id дедуп не запускается — просто создаём запись."""
    repo = _MemJobsDedup()
    repo.jobs["12345"] = _build_canonical()

    vac = VacancyInput(
        source="manual",
        vacancy_id="",
        text=_DUP_TEXT,
        title="No ID",
    )
    result = await persist_scored_with_repo(
        vac, _sample_score(), repo=repo, account_id=1
    )
    # _build_job сохраняет пустую строку как есть
    assert result.job.vacancy_id == ""
    assert len(repo.links) == 0


async def test_no_text_bypasses_dedup():
    """Без текста дедуп не запускается (нечего сравнивать) — но VacancyInput требует
    min_length=50, поэтому даём минимально валидный текст."""
    repo = _MemJobsDedup()
    repo.jobs["12345"] = _build_canonical()

    # VacancyInput требует text длиной >= 50, поэтому даём минимальный текст
    vac = VacancyInput(
        source="habr",
        vacancy_id="habr_300",
        text="A" * 50,  # минимально валидный, но бессмысленный (нет пересечений)
        title="Empty text",
    )
    result = await persist_scored_with_repo(
        vac, _sample_score(), repo=repo, account_id=1
    )
    assert result.job.vacancy_id == "habr_300"
    assert len(repo.links) == 0


async def test_pg_jobs_repo_satisfies_protocol_with_dedup():
    """PgJobsRepository удовлетворяет JobsRepository (включает dedup-методы)."""
    from core.domains.opportunities.repo import PgJobsRepository

    repo = PgJobsRepository(db=object(), account_id=1)  # type: ignore[arg-type]
    assert isinstance(repo, JobsRepository)
    # Все dedup-методы — присутствуют (проверка без вызова)
    assert callable(repo.find_duplicate_candidates)
    assert callable(repo.add_job_link)
    assert callable(repo.enrich_job)