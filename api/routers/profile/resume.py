"""Вкладка «Резюме» в вебе: чтение/правка структурного резюме (JSON) + gap/ats-fit.

Канон — таблица `resumes` в Postgres
на аккаунт запроса; файл `RESUME_DATA_PATH` остаётся только для bootstrap-окна без аккаунтов и
локального friend-install без Telegram-привязки (см. `core.domains.profile.structured_store`).
Скоринг рендерит markdown из этой модели в рантайме (`to_markdown`), без промежуточного
.md-файла. Правка через `PUT /api/resume/data` сразу пишется в канон и сбрасывает кэш скоринга.
Ошибка записи → 500 (в отличие от read-витрин молча не глотаем: иначе вкладка соврёт владельцу
про сохранение).

M1 (plans/multitenancy_gaps_2026_08_06.md §3.1/§6): весь роутер — за `require_account_context`
(`account_id` из токена запроса), включая ручки, у которых до этого личность терялась
(`/gap`, `/skills`, `/skills/refresh`, `/score-history`, `/search-profile/suggest`,
`/ats-fit/stream`) — онбординг фронта уже гейтит вкладку «Резюме» авторизацией (CLAUDE.md), так
что bootstrap-окно `account=None` сюда не долетает.

Одиночные `strengthen` / `gap-audit` / не-SSE `ats-fit` / `score/refresh` роуты удалены —
без потребителей, веб зовёт только `ats-fit/stream`.
"""

from __future__ import annotations

import logging

from fastapi import APIRouter, BackgroundTasks, Depends, File, HTTPException, UploadFile
from fastapi.responses import StreamingResponse

from api.schemas import (
    GmProfileDiffResponse,
    GmProfileDiscrepancyOut,
    GmProfileIngest,
    GmTrustIngest,
    GmTrustIngestResponse,
    GmTrustStatusOut,
    PrioritySuggestionOut,
    ResumeChatHistory,
    SearchProfileSuggestRequest,
    SearchProfileSuggestResponse,
)
from api.security import AccountContext, require_account_context
from core.domains.profile import (
    EmployerDescriptor,
    InternationalReadiness,
    ResumeData,
    ResumeDataPatch,
    ResumeGapReport,
    build_gap_report,
    current_employer_experience,
    get_or_create_employer_descriptor,
    read_resume_data_for_account,
    save_resume_data,
)
from core.domains.profile.ats_fit import (
    AtsFitAboutPatch,
    AtsFitExperiencePatch,
    AtsFitResult,
    iter_ats_fit_events,
    strengthen_about_block,
    strengthen_experience_block,
)
from core.domains.profile.parse_pdf import ResumePdfParseError, parse_resume_pdf
from core.domains.profile.resume_score import ResumeScoreSnapshot, load_score_history
from core.domains.profile.score_refresh import refresh_resume_score
from core.domains.profile.search_profile_suggest import suggest_search_profile
from core.domains.profile.skill_suggest import (
    SkillSnapshot,
    SkillsPanel,
    SkillStateUpdate,
    SkillSuggestionRow,
    load_skills_panel,
    refresh_snapshot,
    set_user_state,
)
from core.kernel.errors import LlmError

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/api/resume", tags=["resume"])


def _enqueue_score_refresh(
    background: BackgroundTasks, meta_stale: bool | None, *, account_id: int
) -> None:
    """Фоновый полный пересчёт балла, если быстрый путь пометил stale."""
    if meta_stale:
        background.add_task(refresh_resume_score, account_id=account_id)


@router.get("/gap", response_model=ResumeGapReport)
async def get_resume_gap(
    background: BackgroundTasks, account: AccountContext = Depends(require_account_context)
) -> ResumeGapReport:
    """Срез «резюме vs рынок» + балл для аккаунта запроса.

    Быстрый путь: regex-gap + structure/market сейчас; writing/role_fit из снимка/эвристик.
    Если `score_meta.stale` — в фоне запускается extract-LLM refresh (не блокирует ответ).
    """
    report = await build_gap_report(account_id=account.account_id)
    _enqueue_score_refresh(
        background,
        bool(report.score_meta and report.score_meta.stale),
        account_id=account.account_id,
    )
    return report


@router.get("/skills", response_model=SkillsPanel)
async def get_resume_skills(
    account: AccountContext = Depends(require_account_context),
) -> SkillsPanel:
    """Единый список «Навыки и спрос» аккаунта запроса:
    сохранённый снимок целиком («держу»/«добавить»/«лишний»/«переименовать») + `stale`-флаг
    словами.

    Только чтение — никогда не вызывает LLM (пересборка — `POST /skills/refresh`). Заменяет
    удалённый `GET /skill-demand` — единственный источник спроса на навыки теперь этот.
    """
    return await load_skills_panel(account_id=account.account_id)


async def _skills_refresh_sse_payloads(*, account_id: int):
    """SSE-прогресс пересборки снимка навыков (как ats-fit/stream)."""
    try:
        yield {"type": "start", "done": 0, "total": 1, "label": "Разбор требований выборки"}
        snapshot = await refresh_snapshot(account_id=account_id)
        yield {"type": "progress", "done": 1, "total": 1, "label": "Готово"}
        yield {"type": "done", "data": snapshot.model_dump(mode="json")}
    except LlmError as exc:
        logger.error("resume skills/refresh OpenRouter error: %s", exc)
        yield {"type": "error", "detail": str(exc)}
    except Exception as exc:  # noqa: BLE001 — стрим не должен рвать без кадра клиенту
        logger.exception("resume skills/refresh: %s", exc)
        yield {"type": "error", "detail": str(exc)}


@router.post("/skills/refresh", responses={200: {"model": SkillSnapshot}})
async def post_resume_skills_refresh(
    account: AccountContext = Depends(require_account_context),
) -> StreamingResponse:
    """S-05: пересобрать снимок навыков аккаунта запроса. SSE-прогресс, терминальный кадр —
    новый снимок.

    Двойной клик — один прогон (`refresh_snapshot` — single-flight по ключу с account_id).
    """
    from api.streaming import sse_response

    return sse_response(_skills_refresh_sse_payloads(account_id=account.account_id))


@router.patch("/skills", response_model=SkillSuggestionRow)
async def patch_resume_skill_state(
    body: SkillStateUpdate, account: AccountContext = Depends(require_account_context)
) -> SkillSuggestionRow:
    """«Скрыть» / «вернуть» одно предложение снимка аккаунта запроса (Решение 6) — переживает
    перезагрузку."""
    row = await set_user_state(body.skill, body.user_state, account_id=account.account_id)
    if row is None:
        raise HTTPException(status_code=404, detail="навык не найден в текущем снимке")
    return row


@router.get("/data", response_model=ResumeData)
async def get_resume_data(
    account: AccountContext = Depends(require_account_context),
) -> ResumeData:
    """Структурное резюме по полям hh.ru (источник правды вкладки «Резюме»)."""
    return await read_resume_data_for_account(account.account_id)


@router.get("/international", response_model=InternationalReadiness)
async def get_international_readiness(
    account: AccountContext = Depends(require_account_context),
) -> InternationalReadiness:
    """Выведенный международный профиль (без полей ввода). Кэш снимка, без LLM на GET."""
    from core.domains.profile.intl_experience import load_international_readiness

    return await load_international_readiness(account_id=account.account_id)


@router.post("/employer-descriptor", response_model=EmployerDescriptor | None)
async def post_employer_descriptor(
    account: AccountContext = Depends(require_account_context),
) -> EmployerDescriptor | None:
    """Дескриптор текущего работодателя для превью тумблера «Скрывать текущее место» (Э4.2).

    POST, не GET — кэш-или-создать может дёрнуть LLM (get-or-create, не генерит заново при
    повторном вызове с тем же работодателем). Нет текущего места в опыте → `None`.
    """
    resume = await read_resume_data_for_account(account.account_id)
    exp = current_employer_experience(resume)
    if exp is None or not exp.company.strip():
        return None
    return await get_or_create_employer_descriptor(
        account.account_id,
        company=exp.company,
        industry=exp.industry,
        area=exp.area,
        role_context=exp.position,
    )


@router.put("/data", response_model=ResumeData)
async def put_resume_data(
    body: ResumeData,
    background: BackgroundTasks,
    account: AccountContext = Depends(require_account_context),
) -> ResumeData:
    """Сохранить структурное резюме. Скоринг рендерит markdown из JSON; балл — фоном."""
    try:
        saved = await save_resume_data(body, source="resume_put", account_id=account.account_id)
    except OSError as exc:
        logger.error("Резюме: не удалось сохранить структурное резюме: %s", exc)
        raise HTTPException(status_code=500, detail="не удалось сохранить резюме") from exc

    background.add_task(refresh_resume_score, account_id=account.account_id)
    return saved


@router.patch("/data", response_model=ResumeData)
async def patch_resume_data(
    body: ResumeDataPatch,
    background: BackgroundTasks,
    account: AccountContext = Depends(require_account_context),
) -> ResumeData:
    """Точечный автосейв: правит только переданные поля, не весь `ResumeData`.

    read-modify-write — резюме не in-memory стейт браузера, конкурентных правок с других
    вкладок у одного аккаунта, так что риска затереть чужую параллельную правку нет.
    Балл резюме пересчитывается в фоне (не блокирует автосейв на OpenRouter).
    """
    account_id = account.account_id
    current = await read_resume_data_for_account(account_id)
    updates: dict = {}

    if body.personal is not None:
        personal_fields = body.personal.model_dump(exclude_unset=True)
        if personal_fields:
            updates["personal"] = current.personal.model_copy(update=personal_fields)

    if body.position is not None:
        position_fields = body.position.model_dump(exclude_unset=True)
        if position_fields:
            updates["position"] = current.position.model_copy(update=position_fields)

    if body.search_criteria is not None:
        criteria_fields = body.search_criteria.model_dump(exclude_unset=True)
        if criteria_fields:
            updates["search_criteria"] = current.search_criteria.model_copy(update=criteria_fields)

    if body.education_level is not None:
        updates["education_level"] = body.education_level

    if body.education is not None:
        updates["education"] = body.education

    if body.languages is not None:
        updates["languages"] = body.languages

    if body.key_skills is not None:
        updates["key_skills"] = body.key_skills

    if not updates:
        return current

    merged = current.model_copy(update=updates)
    try:
        saved = await save_resume_data(merged, source="resume_patch", account_id=account_id)
    except OSError as exc:
        logger.error("Резюме: не удалось сохранить частичную правку: %s", exc)
        raise HTTPException(status_code=500, detail="не удалось сохранить резюме") from exc

    background.add_task(refresh_resume_score, account_id=account_id)
    return saved


@router.post("/gm-profile-diff", response_model=GmProfileDiffResponse)
async def post_gm_profile_diff(
    body: GmProfileIngest, account: AccountContext = Depends(require_account_context)
) -> GmProfileDiffResponse:
    """Принять getmatch-профиль из расширения, сравнить с Copilot-резюме, вернуть расхождения."""
    from core.domains.profile.gm_profile import ingest_and_diff_gm_profile

    stored, discrepancies = await ingest_and_diff_gm_profile(
        body.profile or {}, account_id=account.account_id
    )
    logger.info("gm-profile-diff: расхождений=%s сохранён=%s", len(discrepancies), stored)
    return GmProfileDiffResponse(
        available=True,
        stored=stored,
        discrepancies=[GmProfileDiscrepancyOut(**d.model_dump()) for d in discrepancies],
    )


@router.get("/gm-profile-diff", response_model=GmProfileDiffResponse)
async def get_gm_profile_diff(
    account: AccountContext = Depends(require_account_context),
) -> GmProfileDiffResponse:
    """Расхождения последнего снимка getmatch с Copilot-резюме (вкладка «Резюме»)."""
    from core.domains.profile.gm_profile import diff_latest_gm_profile

    available, discrepancies = await diff_latest_gm_profile(account_id=account.account_id)
    return GmProfileDiffResponse(
        available=available,
        discrepancies=[GmProfileDiscrepancyOut(**d.model_dump()) for d in discrepancies],
    )


@router.post("/gm-trust", response_model=GmTrustIngestResponse)
async def post_gm_trust(
    body: GmTrustIngest, account: AccountContext = Depends(require_account_context)
) -> GmTrustIngestResponse:
    """Принять чеклист доверия getmatch из расширения, сохранить снимок, вернуть статус."""
    from core.domains.profile.gm_trust import ingest_gm_trust

    stored, status = await ingest_gm_trust(body.trust or {}, account_id=account.account_id)
    logger.info(
        "gm-trust: заполнено=%s/6 доверенный=%s сохранён=%s",
        status.filled_count,
        status.trusted,
        stored,
    )
    return GmTrustIngestResponse(stored=stored, status=GmTrustStatusOut(**status.model_dump()))


@router.get("/gm-trust", response_model=GmTrustStatusOut)
async def get_gm_trust(
    account: AccountContext = Depends(require_account_context),
) -> GmTrustStatusOut:
    """Состояние заполненности профиля getmatch по последнему снимку (вкладка «Резюме»)."""
    from core.domains.profile.gm_trust import latest_gm_trust_status

    status = await latest_gm_trust_status(account_id=account.account_id)
    return GmTrustStatusOut(**status.model_dump())


@router.get("/score-history", response_model=list[ResumeScoreSnapshot])
async def get_resume_score_history(
    limit: int = 30, account: AccountContext = Depends(require_account_context)
) -> list[ResumeScoreSnapshot]:
    """История снимков скора аккаунта запроса (от старых к новым) — тренд между итерациями
    (п.2).

    Нет PG — пустой список (вкладка не падает, просто без тренда).
    """
    try:
        return await load_score_history(limit, account_id=account.account_id)
    except Exception as exc:  # noqa: BLE001 — best-effort, как остальные PG-витрины вкладки
        logger.debug("Резюме: история скора недоступна (нет PG?): %s", exc)
        return []


@router.post("/search-profile/suggest", response_model=SearchProfileSuggestResponse)
async def post_resume_search_profile_suggest(
    body: SearchProfileSuggestRequest,
    account: AccountContext = Depends(require_account_context),
) -> SearchProfileSuggestResponse:
    """Подбор профиля поиска по резюме аккаунта запроса: тип роли, рынок, слайт приоритетов.

    Ничего не сохраняет — фронт принимает через PATCH (пустые оси заполняет, занятые
    предлагает заменить явно).
    """
    try:
        result = await suggest_search_profile(
            account_id=account.account_id, exclude_priorities=body.exclude_priorities
        )
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc
    except LlmError as exc:
        logger.error("resume search-profile/suggest OpenRouter error: %s", exc)
        raise HTTPException(status_code=503, detail=str(exc)) from exc
    return SearchProfileSuggestResponse(
        role_kind=result.role_kind,
        market_segment=result.market_segment,
        priorities=[
            PrioritySuggestionOut(label=p.label, reason=p.reason) for p in result.priorities
        ],
    )


@router.post("/parse-pdf", response_model=ResumeData)
async def post_resume_parse_pdf(
    file: UploadFile = File(...),
    account: AccountContext = Depends(require_account_context),
) -> ResumeData:
    """Извлечь текст из PDF и заполнить ResumeData через LLM (structured output).

    Ничего не сохраняет — фронт подставляет поля в форму, владелец ревьюит и жмёт «Сохранить».
    `account` — только для закрытия периметра (роутер «Резюме» целиком за account-контекстом,
    M1); сама конвертация PDF→JSON не зависит от аккаунта.
    """
    _ = account
    name = (file.filename or "").lower()
    content_type = (file.content_type or "").split(";")[0].strip().lower()
    ok_types = ("application/pdf", "application/octet-stream", "")
    if content_type not in ok_types and not name.endswith(".pdf"):
        raise HTTPException(status_code=400, detail="нужен файл PDF")

    raw = await file.read()
    try:
        return await parse_resume_pdf(raw)
    except ResumePdfParseError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc
    except LlmError as exc:
        logger.error("resume parse-pdf OpenRouter error: %s", exc)
        raise HTTPException(status_code=503, detail=str(exc)) from exc


async def _ats_fit_sse_payloads(*, account_id: int):
    """Доменные события ats-fit + терминальный done/error для SSE."""
    try:
        async for event in iter_ats_fit_events(account_id=account_id):
            yield event
            if event.get("type") == "result":
                yield {"type": "done", "data": event.get("data")}
    except LlmError as exc:
        logger.error("resume ats-fit/stream OpenRouter error: %s", exc)
        yield {"type": "error", "detail": str(exc)}
    except Exception as exc:  # noqa: BLE001 — стрим не должен рвать без кадра клиенту
        logger.exception("resume ats-fit/stream: %s", exc)
        yield {"type": "error", "detail": str(exc)}


@router.post("/ats-fit/stream", responses={200: {"model": AtsFitResult}})
async def post_resume_ats_fit_stream(
    account: AccountContext = Depends(require_account_context),
) -> StreamingResponse:
    """FR2-38 / A-14: SSE-прогресс ats-fit («3/6 блоков») → done|error, для аккаунта запроса.

    `responses={200: AtsFitResult}` — документирует форму `done`-кадра (после удаления
    дублирующего не-SSE `/ats-fit` в F-19 это единственный якорь схемы `AtsFit*` для
    `frontend/src/api/schema.d.ts`); фактический ответ остаётся SSE, не JSON.
    """
    from api.streaming import sse_response

    return sse_response(_ats_fit_sse_payloads(account_id=account.account_id))


@router.post("/ats-fit/experience/{index}", response_model=AtsFitExperiencePatch)
async def post_resume_ats_fit_experience(
    index: int, account: AccountContext = Depends(require_account_context)
) -> AtsFitExperiencePatch:
    """Подогнать под ATS одно место работы (описание) через LLM — кнопка у конкретного блока
    «Опыт работы». Ничего не сохраняет: правку владелец принимает в форме.
    """
    try:
        return await strengthen_experience_block(index=index, account_id=account.account_id)
    except ValueError as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc
    except LlmError as exc:
        logger.error("resume ats-fit/experience OpenRouter error: %s", exc)
        raise HTTPException(status_code=503, detail=str(exc)) from exc


@router.post("/ats-fit/about", response_model=AtsFitAboutPatch)
async def post_resume_ats_fit_about(
    account: AccountContext = Depends(require_account_context),
) -> AtsFitAboutPatch:
    """Подогнать под ATS блок «Обо мне» через LLM — кнопка над блоком «Обо мне».
    Ничего не сохраняет: правку владелец принимает в форме.
    """
    try:
        return await strengthen_about_block(account_id=account.account_id)
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc
    except LlmError as exc:
        logger.error("resume ats-fit/about OpenRouter error: %s", exc)
        raise HTTPException(status_code=503, detail=str(exc)) from exc


@router.get("/chat", response_model=ResumeChatHistory)
async def get_resume_chat(
    account: AccountContext = Depends(require_account_context),
) -> ResumeChatHistory:
    """История чата по резюме аккаунта запроса (хронологически). Нет PG → пустой список.

    `attachments`/`reply_to_message_id` (паритет с чатом «Рынка», миграция 0120) — раньше
    композер был упрощённым (только текст), теперь отвечает/вкладывает как чат по рынку.
    """
    from api.routers.market.mappers import market_chat_history
    from core.domains.assistant.attachments.service import load_for_resume_chat_messages
    from core.domains.assistant.resume_chat import load_resume_chat

    messages = await load_resume_chat(account_id=account.account_id)
    message_ids = [m.id for m in messages if m.id is not None]
    attachments = await load_for_resume_chat_messages(message_ids, account_id=account.account_id)
    # ResumeChatMessageOut структурно идентичен MarketChatMessageOut (id/role/content/
    # reply_to_message_id/attachments/created_at) — переиспользуем готовый маппер, не дублируем.
    return market_chat_history(messages, attachments)  # type: ignore[arg-type]


@router.delete("/chat")
async def clear_resume_chat_endpoint(
    account: AccountContext = Depends(require_account_context),
) -> dict[str, int]:
    """Очистить чат по резюме аккаунта запроса. Возвращает число удалённых строк."""
    from core.domains.assistant.resume_chat import clear_resume_chat

    removed = await clear_resume_chat(account_id=account.account_id)
    return {"removed": removed}


@router.delete("/chat/messages/{message_id}")
async def delete_resume_chat_message_endpoint(
    message_id: int,
    account: AccountContext = Depends(require_account_context),
) -> dict[str, bool]:
    """Удалить одну реплику (выделение → Удалить, зеркало `DELETE /market/chat/messages/{id}`
    чата по рынку)."""
    from core.domains.assistant.resume_chat import delete_resume_chat_messages

    removed = await delete_resume_chat_messages([message_id], account_id=account.account_id)
    return {"deleted": removed > 0}
