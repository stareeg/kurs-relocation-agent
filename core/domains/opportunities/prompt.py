"""Сборка system-промпта скоринга (задача 1.5, подшаг 5).

Статичный префикс (роль + резюме + instructions + правила вывода + анти-галлюцинации)
живёт в `prompts/opportunities/system.md` как шаблон с плейсхолдерами и помечается под
prompt caching. Динамический хвост — блок «Выученные предпочтения» (Role=2, заполнится
в 3.4); сейчас пуст и не кэшируется. Резюме читается из JSON (`resume_data.json` по
`RESUME_DATA_PATH`) и рендерится в markdown в рантайме через `to_markdown`; instructions
несёт и схему выходного скоринга.
"""

from __future__ import annotations

from functools import lru_cache
from pathlib import Path

from core.config import CoreSettings, get_settings
from core.domains.opportunities.anti_hallucination import (
    ANTI_HALLUCINATION_JSON,
    ANTI_HALLUCINATION_RULES,
)
from core.domains.opportunities.llm import INSTRUCTIONS, JOB_SEARCH_SYSTEM
from core.domains.profile.identity import candidate_identity_line, candidate_specialization_line
from core.domains.profile.model import ResumeData, to_markdown
from core.domains.profile.structured_store import read_default_resume_data
from core.kernel.text import SPOTLIGHT_RULE

# Плейсхолдеры в prompts/opportunities/system.md — подменяем .replace(), не .format()
# (резюме/instructions содержат фигурные скобки markdown — format() их ломает).
_RESUME_TOKEN = "{{RESUME}}"
_INSTRUCTIONS_TOKEN = "{{INSTRUCTIONS}}"
_ANTI_HALLUCINATION_TOKEN = "{{ANTI_HALLUCINATION}}"
# Правило спотлайтинга (2.7): текст вакансии приходит между маркерами как данные, не инструкции.
_SPOTLIGHT_TOKEN = "{{SPOTLIGHT}}"
# FR-6: единый токен идентичности кандидата для остальных статических .md-промптов
# (job_search/system.md резюме и так получает целиком через {{RESUME}}, токен ему не нужен).
CANDIDATE_IDENTITY_TOKEN = "{{CANDIDATE_IDENTITY}}"


def _read(path_str: str, *, what: str) -> str:
    path = Path(path_str)
    if not path.exists():
        raise FileNotFoundError(f"{what} не найден: {path} (CWD={Path.cwd()})")
    return path.read_text(encoding="utf-8")


@lru_cache(maxsize=1)
def _render_resume(data_path: str) -> str:
    """Отрендерить резюме владельца инсталляции в markdown. Кэшируется по пути к JSON — файловый
    sync-путь для доменов без account_id (офферы/подготовка/HR-черновики/рынок — свои M-этапы,
    plans/multitenancy_gaps_2026_08_06.md §6) и для тестов/bootstrap; account-aware код (M1,
    §3.1) передаёт `data=` явно и в этот кэш не заходит.

    Кэш сбрасывается `clear_resume_cache()` после правки JSON (через `save_resume_data`
    или `publish`), иначе файловый путь продолжит отдавать старый текст.
    """
    settings = get_settings()
    data = read_default_resume_data(settings=settings)
    return to_markdown(data)


def load_instructions(settings: CoreSettings | None = None) -> str:
    """Стратегические предпочтения кандидата (prompts/opportunities/instructions.md). Для offer-compare и Q&A."""
    return _read(INSTRUCTIONS, what="instructions.md")


def load_resume(settings: CoreSettings | None = None, *, data: ResumeData | None = None) -> str:
    """Канонический markdown резюме.

    `data` задан (M1: вызывающий уже резолвил `ResumeData` для конкретного account_id, см.
    `core.domains.profile.structured_store.read_resume_data_for_account`) — рендерим его
    напрямую, без файла/кэша. `data=None` — файловый путь: `resume_data.json` по
    `RESUME_DATA_PATH`, кэшируется по пути (тесты/bootstrap).
    """
    if data is not None:
        return to_markdown(data)
    settings = settings or get_settings()
    return _render_resume(settings.resume_data_path)


@lru_cache(maxsize=1)
def _candidate_identity(data_path: str) -> str:
    """Короткая строка идентичности, кэшируется по пути к JSON вместе с `_render_resume`."""
    settings = get_settings()
    data = read_default_resume_data(settings=settings)
    return candidate_identity_line(data)


def load_candidate_identity(
    settings: CoreSettings | None = None, *, data: ResumeData | None = None
) -> str:
    """«{должность} ({место работы})» кандидата — для system-промптов вне job_search/system.md
    (тот получает резюме целиком через `{{RESUME}}`). Замена ~15 мест ручного дублирования
    "Lead LLM Engineer, ex-Сбер". `data` — см. `load_resume`."""
    if data is not None:
        return candidate_identity_line(data)
    settings = settings or get_settings()
    return _candidate_identity(settings.resume_data_path)


@lru_cache(maxsize=1)
def _candidate_specialization(data_path: str) -> str:
    """Ниша/специализация, кэшируется по пути к JSON вместе с `_render_resume`."""
    settings = get_settings()
    data = read_default_resume_data(settings=settings)
    return candidate_specialization_line(data)


def load_candidate_specialization(
    settings: CoreSettings | None = None, *, data: ResumeData | None = None
) -> str:
    """Ниша/специализация кандидата — подставляется в `{{SPECIALIZATION}}` профилей компаний
    (`core.domains.preparation.interview.company_profiles`) вместо зашитого "ML/LLM".
    `data` — см. `load_resume`."""
    if data is not None:
        return candidate_specialization_line(data)
    settings = settings or get_settings()
    return _candidate_specialization(settings.resume_data_path)


@lru_cache(maxsize=1)
def _candidate_min_salary(data_path: str) -> int:
    """Замена константы `CANDIDATE_MIN_SALARY`, кэшируется вместе с `_render_resume`."""
    settings = get_settings()
    data = read_default_resume_data(settings=settings)
    return data.position.salary_min or 0


def load_candidate_min_salary(
    settings: CoreSettings | None = None, *, data: ResumeData | None = None
) -> int:
    """Минимальный порог зарплаты кандидата из «Желаемой должности» резюме — раньше
    жил как хардкод `CANDIDATE_MIN_SALARY = 400_000` в `core.domains.opportunities.salary_estimator`.
    0, если в резюме зарплата не указана — тогда порог не гейтит `meets_min` (сравнение с 0
    всегда true). `data` — см. `load_resume`."""
    if data is not None:
        return data.position.salary_min or 0
    settings = settings or get_settings()
    return _candidate_min_salary(settings.resume_data_path)


def clear_resume_cache() -> None:
    """Сбросить lru-кэш резюме. Зовётся после правки JSON (публикация из вкладки «Резюме»,
    JS-2.1), иначе скоринг продолжит отдавать старый текст из кэша."""
    _render_resume.cache_clear()
    _candidate_identity.cache_clear()
    _candidate_specialization.cache_clear()
    _candidate_min_salary.cache_clear()
    # SearchProfile кэшируется отдельно (шаг 2/3) — без сброса после save скоринг/аналитика
    # читали бы старые role_kind / market_segment / зарплату.
    from core.domains.profile.profile import clear_search_profile_cache

    clear_search_profile_cache()


def build_system_prompt_text(
    settings: CoreSettings | None = None, *, data: ResumeData | None = None
) -> str:
    """Статичный текст system-промпта (для кэш-префикса). `data` — см. `load_resume`; скоринг
    (hot path) резолвит `ResumeData` аккаунта запроса и передаёт сюда явно."""
    settings = settings or get_settings()
    template = _read(JOB_SEARCH_SYSTEM, what="Шаблон opportunities/system.md")
    instructions = _read(INSTRUCTIONS, what="instructions.md")
    resume = to_markdown(data) if data is not None else _render_resume(settings.resume_data_path)
    anti = (ANTI_HALLUCINATION_RULES + ANTI_HALLUCINATION_JSON).strip()
    return (
        template.replace(_RESUME_TOKEN, resume)
        .replace(_INSTRUCTIONS_TOKEN, instructions)
        .replace(_ANTI_HALLUCINATION_TOKEN, anti)
        .replace(_SPOTLIGHT_TOKEN, SPOTLIGHT_RULE)
    )


# build_system_message удалён в A-10: сборку кэшируемого system'а (статический префикс +
# `dynamic_tail`) делает `platform.llm.call.run` по флагу `cache_prefix` фичи `job_search`.
