"""Фоновый полный пересчёт балла резюме: extract LLM + снимок в PG."""

from __future__ import annotations

import logging
from collections import OrderedDict
from datetime import UTC, datetime, timedelta

from core.domains.profile.gap import (
    ResumeScoreBreakdown,
    build_gap_report,
    compute_report,
    compute_score_async,
    corpus_fingerprint,
    is_refresh_inflight,
    load_corpus,
    load_top_scored_jobs,
    mark_refresh_inflight,
    put_cached_score,
    resume_text_hash,
    score_cache_key,
)
from core.domains.profile.structured_store import (
    read_resume_data_for_account,
    render_resume_markdown_for_account,
)

logger = logging.getLogger(__name__)

# LLM-refresh не чаще, чем раз в 5 минут на аккаунт **после успешного** пересчёта —
# первичный refresh (last=None) не throttled.
REFRESH_THROTTLE = timedelta(minutes=5)
# Bounded: ключ = account_id, значение — таймстамп последнего refresh. Число аккаунтов невелико,
# но без верхней границы при удалении аккаунта запись остаётся навсегда — тот же anti-pattern
# «dict растёт бесконечно». Лимит с запасом над числом аккаунтов; LRU держит горячие аккаунты.
_LAST_REFRESH_MAX = 64
_last_refresh_at: OrderedDict[int, datetime] = OrderedDict()


def _throttled(account_id: int) -> bool:
    """True, если с прошлого refresh прошло меньше REFRESH_THROTTLE."""
    last = _last_refresh_at.get(account_id)
    if last is None:
        return False
    return datetime.now(UTC) - last < REFRESH_THROTTLE


def _mark_throttled(account_id: int) -> None:
    _last_refresh_at[account_id] = datetime.now(UTC)
    _last_refresh_at.move_to_end(account_id)
    while len(_last_refresh_at) > _LAST_REFRESH_MAX:
        _last_refresh_at.popitem(last=False)


async def refresh_resume_score(
    *, account_id: int, db: object | None = None, force: bool = False
) -> ResumeScoreBreakdown | None:
    """Полный recompute (writing+role_fit LLM) и запись снимка аккаунта запроса. Идемпотентен
    по cache_key (M1: cache_key сам по себе содержит resume_hash — резюме разных аккаунтов
    даёт разные хэши, коллизия возможна только при побайтово одинаковых резюме).

    `force=False` + свежий refresh → пропуск (throttling), чтобы UI не крутил «Обновляю»
    на каждый автосейв."""
    if not force and _throttled(account_id):
        logger.info(
            "score_refresh: throttled (повтор < %s мин) account=%s",
            int(REFRESH_THROTTLE.total_seconds() // 60),
            account_id,
        )
        return None

    resume_text = await render_resume_markdown_for_account(account_id, db=db)  # type: ignore[arg-type]
    data = await read_resume_data_for_account(account_id, db=db)  # type: ignore[arg-type]

    from core.domains.profile.score_criteria import left_panel_gaps, left_panel_hints

    gaps = left_panel_gaps(data)
    if gaps:
        from core.platform.observability import event

        event(
            logger,
            "СОБЫТИЕ",
            "score_refresh пропущен: left_panel_gaps=%s",
            gaps,
            account_id=account_id,
            gaps=gaps,
            hints=left_panel_hints(data),
        )
        return None

    try:
        corpus = await load_corpus(account_id=account_id, db=db)
    except Exception as exc:  # noqa: BLE001
        logger.debug("score_refresh: корпус недоступен: %s", exc)
        corpus = []
    try:
        top_jobs_texts = await load_top_scored_jobs(10, account_id=account_id, db=db)
    except Exception as exc:  # noqa: BLE001
        logger.debug("score_refresh: топ-вакансии недоступны: %s", exc)
        top_jobs_texts = []

    corpus_texts = [x for _, _, x in corpus]
    report = compute_report(
        corpus_texts, resume_text, market_segment=data.search_criteria.market_segment
    )
    r_hash = resume_text_hash(resume_text)
    c_fp = corpus_fingerprint(report.corpus_size, top_jobs_texts)
    key = score_cache_key(r_hash, c_fp)

    if is_refresh_inflight(key):
        return None
    mark_refresh_inflight(key, True)
    try:
        score = await compute_score_async(
            data,
            resume_text,
            report,
            top_jobs_texts,
            account_id=account_id,
            corpus_texts=corpus_texts,
        )
        put_cached_score(r_hash, c_fp, score)
        try:
            from core.domains.profile.resume_score import save_score_snapshot

            await save_score_snapshot(
                score,
                account_id=account_id,
                resume_hash=r_hash,
                corpus_fp=c_fp,
                writing_ready=True,
                role_fit_ready=True,
                db=db,  # type: ignore[arg-type]
            )
        except Exception as exc:  # noqa: BLE001
            logger.debug("score_refresh: снимок не записан: %s", exc)
        _mark_throttled(account_id)
        logger.info(
            "score_refresh: ok account=%s total=%s writing=%s role_fit=%s",
            account_id,
            score.total,
            score.writing,
            score.role_fit,
        )
        return score
    finally:
        mark_refresh_inflight(key, False)


async def schedule_refresh_if_stale(*, account_id: int) -> bool:
    """Проверить быстрый gap: если stale и не inflight — запустить refresh. True = запустили."""
    report = await build_gap_report(account_id=account_id)
    if report.score_blocked:
        return False
    meta = report.score_meta
    if meta is None or not meta.stale or meta.refreshing:
        return False
    key = score_cache_key(meta.resume_hash, meta.corpus_fp)
    if is_refresh_inflight(key):
        return False
    await refresh_resume_score(account_id=account_id)
    return True


__all__ = ["refresh_resume_score", "schedule_refresh_if_stale"]
