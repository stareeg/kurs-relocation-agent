"""Транспортные схемы API: prep."""

from __future__ import annotations

from datetime import datetime
from typing import Literal

from pydantic import BaseModel, Field

from api.schemas.attachments import AttachmentOut
from core.domains.assistant.attachments.models import AttachmentRoute
from core.domains.opportunities.models import ScoreResult
from core.domains.preparation.models import (
    DebriefAnalysis,
    PrepStage,
)

# --- Подготовка к этапам: вкладка «Подготовка» в вебе ---


class PrepGenerateRequest(BaseModel):
    """Сгенерировать прицельную подготовку под этап по конкретной вакансии (LLM).

    Текст вакансии + оценка прокидываются из карточки воронки (как у Q&A), чтобы не зависеть
    от наличия записи в PG. `stage` — тип этапа (screening/tech/system_design/final/hr_final).
    """

    stage: PrepStage = "screening"
    vacancy_text: str | None = None
    title: str | None = None
    company: str | None = None
    salary_text: str | None = None
    score: ScoreResult | None = None
    # Слабые темы из разбора прошлого собеса (→ JS-4): генерация делает на них упор.
    focus_topics: list[str] = Field(default_factory=list)


class PrepPackRequest(BaseModel):
    """Собрать бриф подготовки под этап конкретной вакансии (LLM), RD-16.

    Контекст вакансии передаётся напрямую (как `PrepGenerateRequest») — не зависит от записи в PG.
    """

    stage: PrepStage = "tech"
    vacancy_text: str | None = None
    title: str | None = None
    company: str | None = None
    salary_text: str | None = None
    score: ScoreResult | None = None


class PrepPackRegenerateResponse(BaseModel):
    """Свежесобранный бриф — кандидат для ревью (фронт подсвечивает diff до сохранения).

    `input_hash` — хэш входа этой сборки; фронт возвращает его в `PrepPackSaveRequest`,
    чтобы повторная сборка с тем же входом не звала LLM заново.
    """

    text: str
    input_hash: str = ""


class PrepPackSaveRequest(BaseModel):
    """Сохранить принятый бриф подготовки (upsert по vacancy_id+stage)."""

    stage: PrepStage = "tech"
    content: str = Field(default="", max_length=20_000)
    input_hash: str = ""


class PrepQuestionOut(BaseModel):
    """Вопрос подготовки: категория (raw, лейблы рисует фронт без эмодзи) + текст + подсказка +
    готовый ответ (markdown: текст/код/схема).

    `answer` — почти дословный ответ, который кандидат может воспроизвести на собеседовании;
    для старых записей (без ответа) — пустая строка, фронт тогда не рисует блок ответа.
    """

    category: str
    text: str
    hint: str = ""
    answer: str = ""
    # RD-22: "asked" — реально выпал на этапе, "unused" — не пригодился, None — ещё не сматчено.
    outcome: Literal["asked", "unused"] | None = None
    # RD-22b: как кандидат ответил на этот вопрос (по расшифровке собеса): confident/medium/weak.
    # None — ответа в расшифровке нет («Под вопросом» на фронте) или вопрос ещё не сматчен.
    mastery: Literal["confident", "medium", "weak"] | None = None
    # PREP-4: ярлык пачки, добавленной чатом («Kafka/Flink») — None у вопросов первичной генерации.
    topic: str | None = None


class PrepCompanyProfile(BaseModel):
    """Распознанный профиль компании: подгоняет состав подготовки под её формат."""

    key: str
    name: str
    summary: str = ""


class PrepResult(BaseModel):
    """Подготовка под этап: вопросы + чеклист «за 3 часа до». `source` различает свежую
    генерацию, сохранённую сессию и пустой ответ (есть только статический чеклист).
    `company_profile` — распознанный по вакансии формат компании (None — общая подготовка)."""

    vacancy_id: str
    stage: str
    stage_label: str
    questions: list[PrepQuestionOut] = Field(default_factory=list)
    checklist: list[str] = Field(default_factory=list)
    framework: list[str] = Field(default_factory=list)
    generated_at: datetime | None = None
    source: Literal["generated", "saved", "empty"] = "empty"
    company_profile: PrepCompanyProfile | None = None


# --- Чат подготовки по вакансии (вкладка «Технички», режим «Подготовка») ---
# Накопительная лента реплик user/assistant под вакансию. Общая для всех этапов: владелец может
# просить «сгенерируй ещё пачку вопросов», «объясни подробнее», задавать встречные вопросы.
# История переживает перезагрузку и переиспользуется между сессиями подготовки.


class PrepChatMessageOut(BaseModel):
    """Реплика чата подготовки. role: user (владелец) | assistant (LLM)."""

    id: int
    vacancy_id: str
    role: Literal["user", "assistant"]
    content: str
    created_at: datetime | None = None
    # Реплика-источник (composer «Ответить») — несёт только реплика владельца.
    reply_to_message_id: int | None = None
    # Картинки-вложения (Э3-1, план chat_image_attachments): пусто — реплика без картинок.
    attachments: list[AttachmentOut] = Field(default_factory=list)


class PrepChatHistory(BaseModel):
    """История чата подготовки по вакансии (хронологически). Нет PG → пустой список."""

    vacancy_id: str
    items: list[PrepChatMessageOut] = Field(default_factory=list)


class PrepChatRequest(BaseModel):
    """Сообщение в чат подготовки. Контекст вакансии + история (как у Q&A) — LLM отвечает
    с учётом того, что уже обсуждалось в чате. `history` копится клиентом, бэк стейтлесс."""

    message: str = Field(min_length=1, max_length=4000)
    history: list[PrepChatMessageOut] = Field(default_factory=list, max_length=40)
    # Контекст вакансии (как у prep/Q&A) — не зависит от наличия записи в PG.
    vacancy_text: str | None = None
    title: str | None = None
    company: str | None = None
    salary_text: str | None = None
    score: ScoreResult | None = None
    # Этап и фокус-темы — чтобы ответы были в контексте текущего этапа подготовки.
    stage: PrepStage = "tech"
    focus_topics: list[str] = Field(default_factory=list)
    # Composer «Ответить» — id реплики-источника (см. reply_to_message_id в chat.py у HR-чата).
    reply_to_message_id: int | None = None
    # Картинки-вложения текущей реплики (Э3-1, план chat_image_attachments): готовые id из
    # POST /api/attachments — инлайном в модель уходят только они, не вся история (плана).
    attachment_ids: list[int] = Field(default_factory=list)


class PrepChatResponse(BaseModel):
    """Ответ ассистента в чат подготовки. `message` — сохранённая реплика ассистента.

    PREP-3: если ассистент распознал просьбу «ещё пачку вопросов», `questions` — новые карточки
    (уже сохранены в `prep_sessions`, дедуп по тексту), `topic` — короткий ярлык пачки. Пустой
    список/`None` — обычный ответ без новых карточек.
    """

    message: PrepChatMessageOut
    questions: list[PrepQuestionOut] = Field(default_factory=list)
    topic: str | None = None


class PrepParseExternalRequest(BaseModel):
    """Распарсить внешнюю переписку с LLM → пачка уже отработанных вопросов (с укороченными ответами).

    Лимит намеренно большой: 10-15 длинных Q&A из внешнего чата не должны отрезаться.

    attachment_ids (Э4-2, план chat_image_attachments) — скрины переписки с внешним ИИ: можно
    вместо текста, можно вместе с ним (`transcript` может быть пустым, если весь дамп — скрины).
    Картинки, распознанные НЕ как переписка (сторонний материал/схема), сервис сам отправляет
    через обычный чат подготовки («вложение диалога», плана) — отдельного поля для этого не
    нужно.
    attachment_routes (Э4-3) — ярлык-переключатель ветки с чипа композера, только для вложений,
    где владелец переопределил угадку классификатора (см. `ConversationImportRequest`).
    """

    transcript: str = Field(default="", max_length=2_000_000)
    stage: PrepStage = "tech"
    vacancy_text: str | None = None
    title: str | None = None
    company: str | None = None
    salary_text: str | None = None
    score: ScoreResult | None = None
    attachment_ids: list[int] = Field(default_factory=list)
    attachment_routes: dict[int, AttachmentRoute] = Field(default_factory=dict)


class PrepTopicOut(BaseModel):
    """Тема готовности под вакансию+этап (weak → medium → confident)."""

    topic: str
    level: Literal["weak", "medium", "confident"] = "weak"
    packs_reviewed: int = 0


class PrepTopicsResponse(BaseModel):
    vacancy_id: str
    stage: str
    items: list[PrepTopicOut] = Field(default_factory=list)


class PrepTopicsGenerateRequest(BaseModel):
    """Сгенерировать темы, которые могут спросить по вакансии (LLM)."""

    stage: PrepStage = "tech"
    vacancy_text: str | None = None
    title: str | None = None
    company: str | None = None
    salary_text: str | None = None
    score: ScoreResult | None = None
    force: bool = False


class PrepTopicsReviewRequest(BaseModel):
    """Засчитать раскрытие ответа по темам (после клика на вопрос в ленте).

    Либо явный `topics`, либо `question_text` - тогда бэкенд в фоне мапит вопрос на каталог
    через LLM (extract) и засчитывает совпавшие темы. Пользователя не напрягаем выбором.
    """

    stage: PrepStage = "tech"
    topics: list[str] = Field(default_factory=list, max_length=40)
    question_text: str | None = None
    question_topic_hint: str | None = None
    answer_excerpt: str | None = None


class PrepTopicExpandRequest(BaseModel):
    """П.5c: раскрыть тему из разбора реального собеса (LLM, basic tier).

    Контекст вакансии — те же поля, что и в `PrepTopicsGenerateRequest` (текст/название/компания/вилка/
    оценка). Stateles: ничего не пишет в БД, кэшируется через общий llm_result_cache по теме.
    """

    stage: PrepStage = "tech"
    topic: str = Field(..., min_length=1, max_length=400)
    vacancy_text: str | None = None
    title: str | None = None
    company: str | None = None
    salary_text: str | None = None
    score: ScoreResult | None = None


class PrepTopicExpandResponse(BaseModel):
    """Markdown-шпаргалка по теме: что входит, типовые вопросы, что почитать."""

    topic: str
    markdown: str


# --- Контекст для оверлея sobes.tech (вкладка «Технички», кнопка справа от чата) ---
# Структурированный markdown, который владелец вставляет в оверлей перед собесом, чтобы LLM
# собеса понимала формат общения и стиль ответов владельца. Регенерируется по кнопке, не авто:
# владелец решает, когда обновлять «шпаргалку» под конкретный собес.


class PrepSobesContextRequest(BaseModel):
    """Сгенерировать контекст-шпаргалку для оверлея sobes.tech под текущий этап вакансии.

    Берёт сохранённые вопросы+ответы prep-сессии и историю чата подготовки по вакансии,
    синтезирует компактный markdown: формат собеса, ключевые темы, стиль ответов, готовые
    тезисы по темам. Без LLM-вызова в простейшем случае — но для качества ответов LLM.
    """

    stage: PrepStage = "tech"
    # Контекст вакансии (как везде) — на случай, если prep-сессии/чата ещё нет.
    vacancy_text: str | None = None
    title: str | None = None
    company: str | None = None
    salary_text: str | None = None
    # Если true — принудительно LLM-генерация даже при пустых prep/чате (даст универсальный
    # контекст под формат этапа). False (по умолчанию) — пусто, если данных нет.
    force: bool = False


class PrepSobesContextResponse(BaseModel):
    """Готовый markdown-контекст для sobes.tech (≤3900 символов).

    `available=false` — нечего собирать (нет текста вакансии и подготовки).
    """

    available: bool = False
    markdown: str = ""
    stage: PrepStage
    stage_label: str
    char_count: int = 0
    char_limit: int = 3900
    generated_at: datetime | None = None


# --- Экспорт полного контекста для внешнего LLM (вкладка «Технички») ---
# Владелец продолжает подготовку к финалу во внешнем Claude/Gemini — вставляет этот текст первым
# сообщением нового диалога вместо ручного пересказа вакансии/переписки/расшифровок.


class PrepExportContextResponse(BaseModel):
    """Полный текст контекста вакансии (+ оффер, HR-переписка, расшифровки, проработанные
    вопросы этапа) для вставки в сторонний LLM-диалог."""

    text: str


# --- Разбор собеса: вкладка «Разбор» в вебе ---


class DebriefAnalyzeRequest(BaseModel):
    """Разобрать транскрипт прошедшего собеса (LLM).

    Транскрипт — главный вход; текст вакансии и оценка прокидываются из карточки воронки (как у
    Q&A/prep), чтобы не зависеть от записи в PG. `stage` — тип этапа (контекст для разбора).

    `attachment_ids` (Э4-4, план chat_image_attachments) — скрины собеса/транскрипции: их текст
    владелец уже вмешал в `transcript` через композер (§3 плана «носитель текста» — распознанный
    текст дописывается в поле расшифровки и виден до отправки), сюда id попадают только чтобы
    привязать картинки к сохранённому разбору и показать их в карточке.
    """

    transcript: str
    stage: PrepStage = "tech"
    vacancy_text: str | None = None
    title: str | None = None
    company: str | None = None
    salary_text: str | None = None
    score: ScoreResult | None = None
    # UX2-9: конкретный этап цепочки (interview_stages.id), которому принадлежит этот транскрипт —
    # None, если владелец не выбрал (цепочка пуста/нет подходящего этапа).
    interview_stage_id: int | None = None
    attachment_ids: list[int] = Field(default_factory=list)


class DebriefResult(BaseModel):
    """Структурный разбор собеса: сигнал next steps + сильные/слабые ответы + темы в подготовку.

    `analysis` — доменный разбор (`core.domains.preparation.models.DebriefAnalysis`); `signal_label` —
    человекочитаемый сигнал без эмодзи для веба (ядро держит подписи с эмодзи под бота).
    `format_label` — подпись автоопределённого формата интервью
    (`analysis.interview_format`), без эмодзи, тот же паттерн.
    `id`/`created_at` — заполнены, если разбор персистнут (нет PG → None, разбор всё равно отдан).
    Та же схема возвращается в истории разборов (`DebriefHistory`), фронт рендерит единым типом.
    `attachments` (Э4-4) — скрины собеса/транскрипции, привязанные к этому разбору; их
    распознанный текст уже вошёл в `transcript` до анализа, здесь они только для показа в карточке.
    """

    vacancy_id: str
    stage: PrepStage = "tech"
    stage_label: str
    signal_label: str
    format_label: str = ""
    analysis: DebriefAnalysis
    transcript: str = ""  # исходный транскрипт — чтобы можно было поправить и переразобрать
    id: int | None = None
    # UX2-9: этап цепочки, к которому привязан этот разбор (None — без привязки).
    interview_stage_id: int | None = None
    # DBR-5: жёлтый (pending) → зелёный (advanced) / красный (rejected) по факту переписки с HR.
    resolution: Literal["pending", "advanced", "rejected"] = "pending"
    resolved_at: datetime | None = None
    resolved_note: str = ""
    created_at: datetime | None = None
    attachments: list[AttachmentOut] = Field(default_factory=list)


class DebriefTranscriptPatch(BaseModel):
    """UX5-5: точечная правка текста транскрипта (дровер-чат) без перезапуска LLM-анализа."""

    transcript: str = Field(min_length=1, max_length=100_000)


class DebriefHistory(BaseModel):
    """История разборов по вакансии (накопление): свежие первыми. Нет PG → пустой список."""

    vacancy_id: str
    items: list[DebriefResult] = Field(default_factory=list)


class DebriefStageMark(BaseModel):
    """Одна отметка «по этой вакансии расшифровка уже разобрана» — vacancy_id + этапы."""

    vacancy_id: str
    stages: list[str] = Field(default_factory=list)


class DebriefStageIndex(BaseModel):
    """Индекс расшифровок аккаунта для рельса вакансий (Скрининги/Технички).

    Рельс показывает отметку «расшифровка есть» на карточке — без этого индекса пришлось бы
    тянуть полную историю разборов на каждую карточку списка. Тут только ключи.
    """

    items: list[DebriefStageMark] = Field(default_factory=list)


class DebriefJobStarted(BaseModel):
    """DBR-2: ответ на `POST /analyze` — разбор запущен в фоне, отдаём сразу (202).

    Результат приходит через опрос `GET /analyze/{job_id}`, а не в теле этого ответа — сам
    LLM-вызов может занимать десятки секунд, и клиент не должен держать HTTP-соединение открытым
    всё это время.
    """

    job_id: str
    status: str = "running"


class DebriefJobStatus(BaseModel):
    """DBR-2: статус фоновой задачи разбора (`running|done|error`).

    `result` заполнен только при `status == "done"`; `error` — человекочитаемое сообщение при
    `status == "error"` (таймаут LLM, бюджет, невалидный транскрипт и т.п.).
    """

    status: str
    result: DebriefResult | None = None
    error: str | None = None


__all__ = [
    "PrepGenerateRequest",
    "PrepPackRequest",
    "PrepPackRegenerateResponse",
    "PrepPackSaveRequest",
    "PrepQuestionOut",
    "PrepCompanyProfile",
    "PrepResult",
    "PrepChatMessageOut",
    "PrepChatHistory",
    "PrepChatRequest",
    "PrepChatResponse",
    "PrepParseExternalRequest",
    "PrepTopicOut",
    "PrepTopicsResponse",
    "PrepTopicsGenerateRequest",
    "PrepTopicsReviewRequest",
    "PrepSobesContextRequest",
    "PrepSobesContextResponse",
    "PrepExportContextResponse",
    "DebriefAnalyzeRequest",
    "DebriefResult",
    "DebriefTranscriptPatch",
    "DebriefHistory",
    "DebriefJobStarted",
    "DebriefJobStatus",
]
