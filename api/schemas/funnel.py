"""Схемы воронки, HR-тредов, чатов-контекстов и этапов собеседований.

Публичный реэкспорт — ``from api.schemas import …``.
"""

from __future__ import annotations

from datetime import datetime
from typing import Literal

from pydantic import BaseModel, Field

from api.schemas.attachments import AttachmentOut
from core.domains.assistant.attachments.models import AttachmentRoute
from core.domains.preparation.models import (
    InterviewStageType,
)

HrChannel = Literal["telegram", "hh", "getmatch", "email", "phone", "other"]

MessageKind = Literal["hr_in", "hr_out", "llm_user", "llm_assistant"]


class FunnelStatusUpdate(BaseModel):
    """Смена статуса воронки. `status` — каноническое значение FunnelStatus («Отклик»…)."""

    vacancy_id: str = Field(min_length=1)
    status: str = Field(min_length=1)
    cover_letter: str | None = Field(default=None, description="Сопроводительное после отклика")
    published_at: str | None = Field(default=None, description="Дата публикации (если ещё нет)")
    offer_at: str | None = Field(default=None, description="Дата оффера (YYYY-MM-DD HH:MM)")
    # Идентичность вакансии из DOM расширения — чтобы stub «клик Откликнуться без /score»
    # не писал в БД пустую карточку (company/title оставались None до следующего скоринга).
    title: str | None = Field(default=None, max_length=500, description="Название вакансии")
    company: str | None = Field(default=None, max_length=300, description="Компания")
    # Текст вакансии из DOM — чтобы stub мог сгенерировать сопроводительное без предварительного
    # /score (раньше stub создавался с пустым vacancy_text, и «Сначала оцените вакансию»).
    vacancy_text: str | None = Field(default=None, max_length=100_000, description="Текст вакансии")


class FunnelStatusResponse(BaseModel):
    vacancy_id: str
    status: str | None = None
    source: str | None = None
    # Числовой id строки jobs в БД — чтобы расширение могло сгенерировать сопроводительное
    # даже для stub-вакансии, созданной кликом «Откликнуться» без предварительного /score.
    # Раньше расширение знало id только из ответа /score — клик «Откликнуться» до скоринга
    # создавал stub без id в ответе, и кнопка «Сопроводительное» упиралась в «Сначала оцените».
    job_id: int | None = None
    # Решение «не подавать» (ортогонально статусу воронки) — чтобы расширение отражало пропуск
    # и после перезагрузки страницы, не предлагая снова активную кнопку «Пропустить».
    skipped: bool = False
    # Каноническая причина пропуска (пусто, если skipped=False) — без неё done-state «Пропущено»
    # на новой вкладке/после очистки storage расширения показывался без причины (сам факт
    # skipped переживает перезагрузку, причина раньше — нет).
    skip_reason: str | None = None


class HrThreadCreate(BaseModel):
    """Завести тред переписки с HR под вакансию (контакт/канал)."""

    vacancy_id: str = Field(min_length=1, max_length=64)
    contact_name: str = Field(default="", max_length=300)
    channel: HrChannel = "telegram"
    company: str = Field(default="", max_length=300)


class HrThreadUpdate(BaseModel):
    """Правка треда (PATCH-семантика): None = «не менять». Статус — чипами, контакт — инлайн."""

    status: Literal["active", "waiting", "closed", "archived"] | None = None
    contact_name: str | None = Field(default=None, max_length=300)
    hr_link: str | None = Field(default=None, max_length=500)
    channel: HrChannel | None = None
    company: str | None = Field(default=None, max_length=300)
    pinned: bool | None = None


class HrMessageCreate(BaseModel):
    """Добавить сообщение в тред (ручной ввод, вставка из Telegram). `sent_at` — когда отправлено.

    `kind` авторитетен; если не задан — выводится из `direction` (старый путь in/out).
    """

    direction: Literal["in", "out"] = "in"
    kind: MessageKind | None = None
    body: str = Field(min_length=1, max_length=20_000)
    sent_at: datetime | None = None


class HrMessageOut(BaseModel):
    """Реплика разговора. kind: hr_in (HR→я) | hr_out (я→HR) | llm_user (я→ассистент) | llm_assistant."""

    id: int
    thread_id: int
    direction: str
    kind: str = "hr_in"
    body: str
    sent_at: datetime | None = None
    created_at: datetime | None = None
    # FR3-74: LLM не уверена в авторе при разборе дампа.
    author_uncertain: bool = False
    # Сообщение-источник, если это ответ через composer «Ответить».
    reply_to_message_id: int | None = None
    # Картинки-вложения (Э2-5, план chat_image_attachments): пусто — реплика без картинок.
    attachments: list[AttachmentOut] = Field(default_factory=list)


class HrThreadOut(BaseModel):
    """Тред переписки по вакансии + агрегаты (число сообщений, время последнего) для списка.

    last_hr_kind/last_hr_at — направление и время последней РЕАЛЬНОЙ hr-реплики
    (hr_in/hr_out, без llm_* болтовни с ассистентом): hr_in → ждёт ответа владельца,
    hr_out → ждём ответа HR. None — реальной переписки в треде ещё не было.

    next_stage_type/next_stage_at — ближайший назначенный этап `interview_stages` этой
    вакансии (созвон/собес с известной датой, извлекается фоном из HR-переписки). None — не назначен.

    suggested_funnel_status / suggested_stage_type — предложение сдвинуть воронку по
    сигналу из диалога (чип «Перевести в …?» в шапке). None — нет предложения.
    """

    id: int
    vacancy_id: str
    contact_name: str = ""
    channel: str = "telegram"
    company: str = ""
    status: str = "active"
    pinned: bool = False
    message_count: int = 0
    last_message_at: datetime | None = None
    last_hr_kind: Literal["hr_in", "hr_out"] | None = None
    last_hr_at: datetime | None = None
    next_stage_type: str | None = None
    next_stage_at: datetime | None = None
    suggested_funnel_status: str | None = None
    suggested_stage_type: str | None = None
    created_at: datetime | None = None
    updated_at: datetime | None = None


class FunnelSuggestionApplyResult(BaseModel):
    """Итог клика по чипу FR2-86: применённый статус воронки (или null, если предложения уже нет)."""

    vacancy_id: str
    status: str | None = None
    applied: bool = False


class FunnelSuggestionDismissResult(BaseModel):
    """Итог «снять чип» без смены воронки."""

    vacancy_id: str
    dismissed: bool = False


class HrThreadList(BaseModel):
    """Треды по вакансии (свежие сверху). Нет PG → пустой список (вкладка не падает)."""

    vacancy_id: str
    items: list[HrThreadOut] = Field(default_factory=list)


class HrMessageList(BaseModel):
    """Лента сообщений треда по времени. Нет PG → пустой список."""

    thread_id: int
    items: list[HrMessageOut] = Field(default_factory=list)


class HrDirectionItem(BaseModel):
    """Одна реплика треда на вход LLM-классификатора направления (EXT-H1).

    `kind=None` — DOM-эвристика расширения не нашла надёжного сигнала, нужно определить.
    `index` — позиция в DOM-порядке (тот же, что расширение вернёт в `resolved`).
    """

    index: int
    kind: MessageKind | None = None
    body: str = Field(min_length=1, max_length=20_000)


class HrDirectionClassifyRequest(BaseModel):
    """Тред целиком (известные + неизвестные направления) для батч-классификации."""

    messages: list[HrDirectionItem] = Field(default_factory=list)


class HrDirectionClassifyResponse(BaseModel):
    """`resolved[index]` — направление, определённое LLM для реплики с исходным kind=None.

    Пустой словарь — LLM недоступна/упала или реплик с kind=None не было; расширение падает на
    прежний fallback (пропуск неопознанной реплики), синк остальных не ломается.
    """

    resolved: dict[int, Literal["hr_in", "hr_out"]] = Field(default_factory=dict)


class ConversationMessageIn(BaseModel):
    """Добавить реплику в разговор вакансии вручную (HR-сообщение или своё в HR/ассистенту)."""

    kind: MessageKind = "hr_in"
    body: str = Field(min_length=1, max_length=20_000)
    sent_at: datetime | None = None


class ConversationImportRequest(BaseModel):
    """Вставленный одним куском дамп переписки (из Telegram) — система сама разобьёт и разметит.

    attachment_ids (Э4-1, план chat_image_attachments) — скрины переписки; можно без текста,
    можно вместе с текстом (захватить старые сообщения контекстом) — оба идут в один дамп.
    attachment_routes (Э4-3) — ярлык-переключатель ветки с чипа композера (`attachment_id →
    "correspondence"|"material"`), только для вложений, где владелец переопределил угадку
    классификатора; остальные решаются по `analysis.kind` как раньше.
    """

    text: str = Field(default="", max_length=100_000)
    attachment_ids: list[int] = Field(default_factory=list)
    attachment_routes: dict[int, AttachmentRoute] = Field(default_factory=dict)


class ConversationOut(BaseModel):
    """Разговор по вакансии: тред (метаданные) + полная лента реплик. thread=None — разговора нет."""

    vacancy_id: str
    thread: HrThreadOut | None = None
    messages: list[HrMessageOut] = Field(default_factory=list)
    hr_link: str = ""


class ConversationList(BaseModel):
    """Все разговоры (по всем вакансиям), свежие сверху — верхнеуровневый список-хаб."""

    items: list[HrThreadOut] = Field(default_factory=list)


class ConversationImportResult(BaseModel):
    """Итог импорта дампа: обновлённый разговор + сколько реплик добавлено.

    unrecognized_attachment_ids (Э4-1) — картинки из запроса, не распознанные как переписка:
    в дамп не попали, фронт предлагает приложить их как вложение диалога вместо импорта.
    """

    vacancy_id: str
    thread: HrThreadOut | None = None
    messages: list[HrMessageOut] = Field(default_factory=list)
    hr_link: str = ""
    added: int = 0
    unrecognized_attachment_ids: list[int] = Field(default_factory=list)


class AttentionStage(BaseModel):
    """Ближайший назначенный этап (блок «Скоро собес») — из `interview_stages`."""

    vacancy_id: str
    company: str = ""
    stage_type: str = "hr_screening"
    scheduled_at: datetime | None = None
    format: str = "unknown"


class AttentionStrongJob(BaseModel):
    """Вакансия 80+ без отклика (блок «Свежие сильные») — компактная карточка."""

    vacancy_id: str
    title: str | None = None
    company: str | None = None
    overall_score: int | None = None
    scored_at: datetime | None = None


class TodayAttention(BaseModel):
    """Витрина дня «Чатов»: 4 SQL-агрегата вместо пустой заглушки, ни одного LLM-вызова.

    reply — треды «ждёт меня» (после кулдауна), remind — «ждём их» дольше порога без
    назначенного созвона, upcoming — ближайшие назначенные этапы (`interview_stages`),
    strong_unapplied — вакансии 80+ в «Просмотре» без отклика за последнее время.
    Архивные чаты и пропущенные/отказные вакансии во все четыре блока не попадают.
    """

    reply: list[HrThreadOut] = Field(default_factory=list)
    remind: list[HrThreadOut] = Field(default_factory=list)
    upcoming: list[AttentionStage] = Field(default_factory=list)
    strong_unapplied: list[AttentionStrongJob] = Field(default_factory=list)


class VacancyAttachSuggestRequest(BaseModel):
    """FR2-87: дамп / черновик «Новая вакансия» → найти уже существующую вакансию для привязки."""

    text: str = Field(default="", max_length=100_000)
    company: str = Field(default="", max_length=300)
    vacancy_url: str = Field(default="", max_length=2000)


class VacancyAttachSuggestionOut(BaseModel):
    """Кандидат «Привязать к …?» (чип / пикер в шапке новой вакансии)."""

    vacancy_id: str
    company: str = ""
    title: str | None = None
    match_via: str = "company"
    label: str = ""
    # FR3-73: статус этапа + момент активности (подпись / различение коллизий).
    status: str | None = None
    activity_at: datetime | None = None


class VacancyAttachSuggestResult(BaseModel):
    """Итог поиска: 0 / 1 / много кандидатов.

    `suggestion` — удобство для ровно одного кандидата (иначе null, без silent pick).
    `candidates` — полный список: UI рисует чип (1) или пикер (≥2).
    """

    suggestion: VacancyAttachSuggestionOut | None = None
    candidates: list[VacancyAttachSuggestionOut] = Field(default_factory=list)


class ConversationOutreachRequest(BaseModel):
    """HR написал первым: новая вакансия в воронке + разговор в «Чатах»."""

    company: str = Field(default="", max_length=300)
    position: str = Field(default="", max_length=300)
    contact_name: str = Field(default="", max_length=200)
    hr_link: str = Field(default="", max_length=500)
    vacancy_url: str = Field(default="", max_length=2000)
    initial_text: str = Field(default="", max_length=100_000)
    vacancy_text: str = Field(default="", max_length=100_000)
    first_contact_at: datetime | None = None


class ConversationOutreachResult(BaseModel):
    vacancy_id: str
    thread: HrThreadOut
    scored: bool = False
    conversation: ConversationOut


class ConversationVacancyTextRequest(BaseModel):
    """Полный текст вакансии, вставленный вручную (сайт без автопарсинга) — заменяет бриф."""

    text: str = Field(min_length=50, max_length=100_000)


class ConversationVacancyTextResult(BaseModel):
    vacancy_id: str
    scored: bool = False
    overall_score: float | None = None


class ConversationIdentityRequest(BaseModel):
    """Карандаш в шапке «Чатов»: правка компании/должности (executive-recruiter кейс — роль ещё
    не определена на момент первого контакта, плейсхолдер правится по факту разговора)."""

    company: str = Field(default="", max_length=300)
    title: str = Field(default="", max_length=300)


class ConversationIdentityResult(BaseModel):
    vacancy_id: str
    company: str = ""
    title: str = ""
    scored: bool = False
    overall_score: float | None = None


class InterviewStageOut(BaseModel):
    """Этап цепочки собеса по вакансии (степпер Техничек/дровер/шапка диалога)."""

    id: int
    vacancy_id: str
    stage_type: InterviewStageType
    stage_label: str
    scheduled_at: datetime | None = None
    format: Literal["online", "offline", "unknown"] = "unknown"
    status: Literal["scheduled", "completed", "cancelled", "rescheduled", "failed"] = "scheduled"
    position: int = 0
    notes: str = ""
    source_message_id: int | None = None
    created_at: datetime | None = None


class InterviewStageListResponse(BaseModel):
    vacancy_id: str
    items: list[InterviewStageOut] = Field(default_factory=list)


class InterviewStageCreate(BaseModel):
    """Добавить этап из канона в цепочку вакансии."""

    stage_type: InterviewStageType
    scheduled_at: datetime | None = None
    format: Literal["online", "offline", "unknown"] = "unknown"
    notes: str = Field(default="", max_length=2000)


class InterviewStagePatch(BaseModel):
    """PATCH-семантика: None = не менять."""

    stage_type: InterviewStageType | None = None
    scheduled_at: datetime | None = None
    format: Literal["online", "offline", "unknown"] | None = None
    status: Literal["scheduled", "completed", "cancelled", "rescheduled", "failed"] | None = None
    notes: str | None = Field(default=None, max_length=2000)


class InterviewStageReorderRequest(BaseModel):
    """Новый порядок цепочки: id этапов вакансии в желаемой последовательности."""

    ordered_ids: list[int] = Field(min_length=1, max_length=20)
