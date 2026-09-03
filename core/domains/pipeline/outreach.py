"""Создание вакансии из HR-first контакта (веб «Новая вакансия», Telegram без отклика).

vacancy_id: hh / gm_* из ссылки, иначе синтетический tg_web_*.
published_at = дата первого контакта. Скоринг — когда накопился текст вакансии (≥50 символов).
"""

from __future__ import annotations

import logging
import secrets
from datetime import UTC, datetime

from core.domains.opportunities.jobs import (
    SOURCE_HR_THREAD_STUB,
    Job,
    add_stage,
    extract_getmatch_numeric_id_from_text,
    get_job_by_vacancy_id,
    save_job,
)
from core.domains.opportunities.models import VacancyInput
from core.domains.opportunities.persist import ScoredJob, score_and_persist
from core.domains.pipeline.channel_vacancy_parser import (
    parse_channel_vacancy_post,
    synthesize_vacancy_text,
)
from core.domains.pipeline.hr_import import split_correspondence
from core.domains.pipeline.hr_threads import (
    HrMessage,
    add_message,
    add_messages,
    get_or_create_thread,
    list_messages,
)
from core.domains.pipeline.vacancy_links import extract_primary_job_url, extract_primary_vacancy_id
from core.kernel.schemas.funnel import FunnelStatus

logger = logging.getLogger(__name__)

_MIN_SCORE_TEXT = 50


def resolve_outreach_vacancy_id(vacancy_url: str, text: str) -> str:
    """Ключ вакансии: hh id, gm_{n}, habr_{n} или tg_web_{hex}."""
    combined = "\n".join(p for p in (vacancy_url.strip(), text.strip()) if p)
    hh_id = extract_primary_vacancy_id(combined, vacancy_url.strip())
    if hh_id:
        return hh_id
    gm_num = extract_getmatch_numeric_id_from_text(combined)
    if gm_num:
        return f"gm_{gm_num}"
    return f"tg_web_{secrets.token_hex(8)}"


def _resolve_listing_url(vacancy_id: str, vacancy_url: str, text: str) -> str | None:
    url = (vacancy_url or "").strip() or extract_primary_job_url(text)
    if url:
        return url
    if vacancy_id.isdigit():
        return f"https://hh.ru/vacancy/{vacancy_id}"
    if vacancy_id.startswith("gm_"):
        numeric = vacancy_id[3:]
        if numeric.isdigit():
            return f"https://getmatch.ru/vacancies/{numeric}"
    if vacancy_id.startswith("habr_"):
        numeric = vacancy_id[5:]
        if numeric.isdigit():
            return f"https://career.habr.com/vacancies/{numeric}"
    return None


async def _hr_in_text(vacancy_id: str, *, account_id: int) -> str:
    from core.domains.pipeline.hr_threads import get_primary_thread

    thread = await get_primary_thread(vacancy_id, account_id=account_id)
    if thread is None or thread.id is None:
        return ""
    parts: list[str] = []
    for msg in await list_messages(thread.id, account_id=account_id):
        if msg.kind == "hr_in" and (msg.body or "").strip():
            parts.append(msg.body.strip())
    return "\n\n".join(parts)


async def maybe_score_outreach_vacancy(vacancy_id: str, *, account_id: int) -> bool:
    """Первичный скоринг по HR-тексту, если вакансия ещё без оценки."""
    job = await get_job_by_vacancy_id(vacancy_id, account_id=account_id)
    if job is None:
        return False
    if job.overall_score is not None and (job.vacancy_text or "").strip():
        return False

    hr_text = (await _hr_in_text(vacancy_id, account_id=account_id)).strip()
    if len(hr_text) < _MIN_SCORE_TEXT:
        return False

    # Только переписка с HR как источник — сводим её к тексту вакансии, а не пишем дамп реплик как
    # есть (под спойлером «Текст вакансии» иначе оказывался пересказ диалога).
    vacancy_text = await synthesize_vacancy_text(hr_text)
    extract = await parse_channel_vacancy_post(hr_text)
    company = (job.company or extract.company or "").strip() or None
    title = (job.title or extract.position or "").strip() or None
    published = job.published_at or datetime.now(tz=UTC).isoformat()

    vac = VacancyInput(
        text=vacancy_text or hr_text,
        url=_resolve_listing_url(vacancy_id, job.url or "", hr_text),
        vacancy_id=vacancy_id,
        title=title,
        company=company,
        salary_text=extract.salary_text or job.salary_text,
        work_format=extract.work_format or job.work_format,
        published_at=published,
        source=SOURCE_HR_THREAD_STUB,
        status=FunnelStatus.SCREENING.value,
    )
    try:
        await score_and_persist(vac, account_id=account_id)
        logger.info("outreach: первичный скор vacancy_id=%s len=%d", vacancy_id, len(hr_text))
        return True
    except Exception as exc:  # noqa: BLE001 — скоринг best-effort
        logger.warning("outreach: скоринг не удался (%s): %s", vacancy_id, exc)
        return False


async def maybe_score_outreach_vacancy_safe(vacancy_id: str, *, account_id: int) -> None:
    """Best-effort обёртка для фоновых триггеров: шаги до `score_and_persist` (получение job,
    сборка текста, LLM-парсинг канала) сами по себе не были защищены — упавший здесь исключение
    раньше обрывало всю цепочку `on_incoming_hr_message` ДО `extract_event_safe`/
    `suggest_funnel_from_dialog_safe`, которые шли следом (см. docs/problems.md, извлечение
    времени собеса почти никогда не срабатывало на реальных диалогах)."""
    try:
        await maybe_score_outreach_vacancy(vacancy_id, account_id=account_id)
    except Exception as exc:  # noqa: BLE001 — фоновый best-effort, не роняем остальную цепочку
        logger.warning(
            "outreach: первичный скор vacancy_id=%s упал (best-effort): %s", vacancy_id, exc
        )


async def create_outreach_vacancy(
    *,
    company: str = "",
    position: str = "",
    contact_name: str = "",
    hr_link: str = "",
    vacancy_url: str = "",
    initial_text: str = "",
    vacancy_text: str = "",
    first_contact_at: datetime | None = None,
    account_id: int,
) -> tuple[str, bool]:
    """Создать job + тред + начальные HR-реплики. Возвращает (vacancy_id, scored).

    `vacancy_text` — отдельно вставленный полный текст вакансии (обязанности/требования), когда
    он есть отдельно от переписки с HR (сайт не hh/gm, скопирован вручную). Скорится и парсится
    ОН, а не `initial_text` — `initial_text` остаётся только перепиской, уходит в тред как есть.
    """
    text = (initial_text or "").strip()
    explicit_vacancy_text = (vacancy_text or "").strip()
    score_text = explicit_vacancy_text or text
    vacancy_id = resolve_outreach_vacancy_id(vacancy_url, f"{text}\n{score_text}")
    contact_at = first_contact_at or datetime.now(tz=UTC)
    published_at = contact_at.isoformat()

    existing = await get_job_by_vacancy_id(vacancy_id, account_id=account_id)
    scored = False
    position_norm = position.strip()

    if existing is None:
        listing_url = _resolve_listing_url(vacancy_id, vacancy_url, f"{text}\n{score_text}")
        company_norm = company.strip()
        if not company_norm and score_text:
            extract = await parse_channel_vacancy_post(score_text)
            company_norm = (extract.company or "").strip()
        if not position_norm and score_text:
            extract = await parse_channel_vacancy_post(score_text)
            position_norm = (extract.position or "").strip()

        if len(score_text) >= _MIN_SCORE_TEXT:
            extract = await parse_channel_vacancy_post(score_text)
            # Явно вставленный текст вакансии (сайт без автопарсинга) — это уже её содержание,
            # используем как есть. Когда источник — только переписка с HR, сводим её к тексту
            # вакансии, а не пишем реплики как дамп.
            persisted_text = (
                score_text if explicit_vacancy_text else await synthesize_vacancy_text(score_text)
            )
            vac = VacancyInput(
                text=persisted_text,
                url=listing_url,
                vacancy_id=vacancy_id,
                title=(position_norm or extract.position or None),
                company=company_norm or extract.company or None,
                salary_text=extract.salary_text or None,
                work_format=extract.work_format or None,
                published_at=published_at,
                source=SOURCE_HR_THREAD_STUB,
                status=FunnelStatus.SCREENING.value,
            )
            try:
                await score_and_persist(vac, account_id=account_id)
                scored = True
            except Exception as exc:  # noqa: BLE001
                logger.warning("outreach: create score failed (%s): %s", vacancy_id, exc)
                job = await save_job(
                    Job(
                        vacancy_id=vacancy_id,
                        vacancy_text=persisted_text[:20_000],
                        url=listing_url,
                        company=company_norm or None,
                        title=position_norm or extract.position or None,
                        status=FunnelStatus.SCREENING.value,
                        source=SOURCE_HR_THREAD_STUB,
                        published_at=published_at,
                    ),
                    account_id=account_id,
                )
                if job.id is not None:
                    await add_stage(
                        job.id,
                        FunnelStatus.SCREENING.value,
                        source="outreach",
                        account_id=account_id,
                    )
        else:
            await save_job(
                Job(
                    vacancy_id=vacancy_id,
                    vacancy_text="",
                    url=listing_url,
                    company=company_norm or None,
                    title=position_norm or None,
                    status=FunnelStatus.SCREENING.value,
                    source=SOURCE_HR_THREAD_STUB,
                    published_at=published_at,
                ),
                account_id=account_id,
            )
            job = await get_job_by_vacancy_id(vacancy_id, account_id=account_id)
            if job and job.id is not None:
                await add_stage(
                    job.id, FunnelStatus.SCREENING.value, source="outreach", account_id=account_id
                )

    thread = await get_or_create_thread(
        vacancy_id,
        company=company.strip() or (existing.company if existing else "") or "",
        contact_name=contact_name.strip(),
        channel="telegram",
        account_id=account_id,
    )
    assert thread.id is not None

    if hr_link.strip():
        from core.domains.opportunities.enrichment import merge_enrichment
        from core.domains.pipeline.hr_identity import normalize_hr_link

        try:
            await merge_enrichment(
                vacancy_id,
                hr_link=normalize_hr_link(hr_link),
                contact_at=contact_at,
                account_id=account_id,
            )
        except Exception as exc:  # noqa: BLE001 — enrichment best-effort
            logger.warning("outreach: hr_link не сохранён (%s): %s", vacancy_id, exc)

    if text:
        if "\n" in text and len(text) > 120:
            split = await split_correspondence(text, [], account_id=account_id)
            pairs = split.pairs
            if pairs:
                await add_messages(
                    [
                        HrMessage(
                            thread_id=thread.id,
                            kind=r.kind,
                            body=r.body,
                            sent_at=r.sent_at or contact_at,
                            author_uncertain=r.author_uncertain,
                        )
                        for r in pairs
                    ],
                    account_id=account_id,
                )
            else:
                await add_message(
                    HrMessage(
                        thread_id=thread.id,
                        kind="hr_in",
                        body=text,
                        sent_at=contact_at,
                    ),
                    account_id=account_id,
                )
        else:
            await add_message(
                HrMessage(
                    thread_id=thread.id,
                    kind="hr_in",
                    body=text,
                    sent_at=contact_at,
                ),
                account_id=account_id,
            )

        if not scored:
            scored = await maybe_score_outreach_vacancy(vacancy_id, account_id=account_id)

    return vacancy_id, scored


async def update_vacancy_identity(
    vacancy_id: str, *, company: str, title: str, account_id: int
) -> ScoredJob | Job:
    """Карандаш в шапке «Чатов»: поправить компанию/должность (FR — executive-recruiter кейс:
    экзек-рекрутер выходит на связь ДО того, как определилась конкретная роль — плейсхолдер
    company/title заведён при `create_outreach_vacancy` вслепую, правится по факту разговора).

    Компания/должность — входы `company_fit`/`grade_match`/`role_content_match` в промпте
    скоринга, поэтому вслед за правкой полей пересчитываем скор тем же текстом вакансии (без
    правки текста отдельного пути обновить только эти факторы нет). Пересчёт — только если уже
    есть с чем считать (`vacancy_text` ≥ порога скоринга); иначе просто сохраняем поля — скор
    посчитается сам, когда наберётся текст (см. `maybe_score_outreach_vacancy`).
    """
    job = await get_job_by_vacancy_id(vacancy_id, account_id=account_id)
    if job is None:
        raise ValueError(f"Вакансия не найдена: {vacancy_id}")

    company_norm = company.strip()
    title_norm = title.strip()
    unchanged = (
        company_norm == (job.company or "").strip() and title_norm == (job.title or "").strip()
    )

    from core.domains.opportunities.jobs import update_job_identity

    updated = await update_job_identity(
        vacancy_id, company=company_norm, title=title_norm, account_id=account_id
    )
    if updated is None:
        raise ValueError(f"Вакансия не найдена: {vacancy_id}")

    thread = await get_or_create_thread(vacancy_id, account_id=account_id)
    if thread.id is not None and company_norm and thread.company != company_norm:
        from core.domains.pipeline.hr_threads import update_thread

        await update_thread(thread.id, company=company_norm, account_id=account_id)

    if unchanged or len((job.vacancy_text or "").strip()) < _MIN_SCORE_TEXT:
        return updated

    vac = VacancyInput(
        text=job.vacancy_text,
        url=job.url,
        vacancy_id=vacancy_id,
        title=title_norm or None,
        company=company_norm or None,
        salary_text=job.salary_text,
        area=job.area,
        work_format=job.work_format,
        work_schedule=job.work_schedule,
        total_responses=job.total_responses,
        letter_required=job.letter_required,
        published_at=job.published_at,
        cover_letter_text=job.cover_letter_text,
        employer_id=job.employer_id,
        source=job.source,
        is_archived=job.is_archived,
        status=job.status,
    )
    return await score_and_persist(vac, account_id=account_id)


async def attach_vacancy_text(vacancy_id: str, text: str, *, account_id: int) -> ScoredJob:
    """Прикрепить/заменить полный текст вакансии на уже существующей записи и пересчитать скор.

    Для сайтов без автопарсинга (не hh/gm) — владелец копирует текст вакансии со страницы
    руками. Переносит ВСЕ прочие поля текущей записи (кроме текста и скора) в новый
    `VacancyInput` явно: `save_job` делает `ON CONFLICT ... DO UPDATE SET <col> = excluded.<col>`
    по фиксированному списку колонок (letter_required/cover_letter_text/status и т.д.) — не
    переданное в `VacancyInput` там было бы затёрто дефолтами `None`/`False`.
    """
    job = await get_job_by_vacancy_id(vacancy_id, account_id=account_id)
    if job is None:
        raise ValueError(f"Вакансия не найдена: {vacancy_id}")

    stripped = text.strip()
    extract = await parse_channel_vacancy_post(stripped)
    vac = VacancyInput(
        text=stripped,
        url=job.url,
        vacancy_id=vacancy_id,
        title=job.title or extract.position or None,
        company=job.company or extract.company or None,
        salary_text=job.salary_text or extract.salary_text or None,
        area=job.area,
        work_format=job.work_format or extract.work_format or None,
        work_schedule=job.work_schedule,
        total_responses=job.total_responses,
        letter_required=job.letter_required,
        published_at=job.published_at,
        cover_letter_text=job.cover_letter_text,
        employer_id=job.employer_id,
        source=job.source,
        is_archived=job.is_archived,
        status=job.status,
    )
    return await score_and_persist(vac, account_id=account_id)
