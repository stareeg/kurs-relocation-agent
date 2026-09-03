"""Транспортные схемы API: resume."""

from __future__ import annotations

from datetime import datetime
from typing import Any, Literal, Self

from pydantic import BaseModel, Field, model_validator

from api.schemas.attachments import AttachmentOut
from api.schemas.auto_apply import AutoApplyConfig
from api.schemas.discovery import DiscoveryConfig
from api.schemas.telegram import TelegramPrefs

# --- Резюме: вкладка «Резюме» в вебе ---


class SearchProfileSuggestRequest(BaseModel):
    """Подбор профиля поиска (тип роли / рынок / приоритеты) по резюме — HITL, ничего не пишет."""

    exclude_priorities: list[str] = Field(
        default_factory=list,
        description="Уже выбранные или показанные приоритеты — не повторять в слайте",
    )


class PrioritySuggestionOut(BaseModel):
    label: str = ""
    reason: str = ""


class SearchProfileSuggestResponse(BaseModel):
    role_kind: str = ""
    market_segment: str = ""
    priorities: list[PrioritySuggestionOut] = Field(default_factory=list)


# --- Статистика резюме: time-series отклика рынка (пишет расширение AF-2, читает «Рынок» AF-3) ---


class ResumeStatsIngest(BaseModel):
    """Снимок агрегатных счётчиков резюме с hh (`/applicant/resumes`). Парсит расширение, шлёт
    на заходе. Числа — публичные счётчики своего резюме (CLAUDE.md: HH read-only)."""

    resume_id: str = Field(default="", max_length=128)
    period: str = Field(default="week", max_length=32)
    impressions: int = Field(default=0, ge=0)
    views: int = Field(default=0, ge=0)
    invitations: int = Field(default=0, ge=0)
    recommended_vacancies: int = Field(default=0, ge=0)
    views_delta: int = 0
    invitations_delta: int = 0
    raw: dict[str, Any] = Field(default_factory=dict)


class ResumeStatsIngestResponse(BaseModel):
    """Результат приёма снимка. `persisted=false` — PG лежал (расширение не спамит ошибками,
    не 500); `inserted` — записан новый снимок (false → дубль за день с теми же числами)."""

    persisted: bool = False
    inserted: bool = False


class ResumeViewRow(BaseModel):
    """Строка истории просмотра резюме (`/applicant/resumeview/history`)."""

    employer: str = Field(default="", max_length=300)
    vacancy_title: str = Field(default="", max_length=500)
    vacancy_url: str = Field(default="", max_length=1000)
    viewed_at: datetime | None = None
    resume_id: str = Field(default="", max_length=128)
    raw: dict[str, Any] = Field(default_factory=dict)


class ResumeViewsIngest(BaseModel):
    """Пачка строк истории просмотров с hh. `resume_id` — дефолт для строк без своего."""

    resume_id: str = Field(default="", max_length=128)
    rows: list[ResumeViewRow] = Field(default_factory=list, max_length=500)


class ResumeViewsIngestResponse(BaseModel):
    """Результат приёма строк истории. `inserted` — сколько новых (остальные отсеяны дедупом)."""

    persisted: bool = False
    inserted: int = 0


class ResumeStatPoint(BaseModel):
    """Точка серии: счётчики резюме на момент времени.

    `resume_id` нужен фронту для переключателя hh ↔ getmatch: снимки getmatch
    пишутся с id `getmatch:profile`, hh — с id резюме на площадке.
    """

    captured_at: datetime
    resume_id: str = ""
    impressions: int = 0
    views: int = 0
    invitations: int = 0
    recommended_vacancies: int = 0
    views_delta: int = 0
    invitations_delta: int = 0


class ResumeStatsSeries(BaseModel):
    """Time-series статистики резюме для вкладки «Рынок»: снимки + посчитанная динамика.

    `*_change` — дельта между первым и последним снимком окна (ускорился/замедлился отклик рынка);
    None — данных мало (< 2 снимков). Нет PG → `available=false` и пустая серия (фронт честный
    empty, не 500)."""

    available: bool = False
    points: list[ResumeStatPoint] = Field(default_factory=list)
    latest: ResumeStatPoint | None = None
    impressions_change: int | None = None
    views_change: int | None = None
    invitations_change: int | None = None


# --- Параметры приложения: app_settings key/value ---


class ScoringImportance(BaseModel):
    """Важность критериев 1-5 для UI шкалы в «Резюме» (источник правды отображения)."""

    salary: int = Field(ge=1, le=5)
    work_format: int = Field(ge=1, le=5)
    grade_match: int = Field(ge=1, le=5)
    role_content: int = Field(ge=1, le=5)
    management: int = Field(ge=1, le=5)
    company: int = Field(ge=1, le=5)


class ScoringWeights(BaseModel):
    """Веса критериев overall_score; сумма строго 100.

    `management` раньше назывался `burnout` (анти-выгорание / доля менеджмента).
    `company` — размер и репутация работодателя.
    """

    salary: int = Field(ge=0, le=100)
    work_format: int = Field(ge=0, le=100)
    grade_match: int = Field(ge=0, le=100)
    role_content: int = Field(ge=0, le=100)
    management: int = Field(ge=0, le=100)
    company: int = Field(ge=0, le=100)

    def total(self) -> int:
        return (
            self.salary
            + self.work_format
            + self.grade_match
            + self.role_content
            + self.management
            + self.company
        )

    @model_validator(mode="before")
    @classmethod
    def migrate_legacy_burnout(cls, data: object) -> object:
        """Старые записи app_settings: burnout → management + company."""
        if not isinstance(data, dict):
            return data
        raw = dict(data)
        if "management" not in raw and "burnout" in raw:
            raw["management"] = raw.pop("burnout")
        if "company" not in raw:
            # Перераспределяем к канону 20/20/15/15/15/15, сохраняя относительные пропорции
            # известных ключей, если сумма уже 100 без company.
            known = ["salary", "work_format", "grade_match", "role_content", "management"]
            present = {k: int(raw[k]) for k in known if k in raw}
            if present and sum(present.values()) == 100:
                # Снимаем ~15% пропорционально под company.
                take = 15
                scaled = {k: max(0, round(v * (100 - take) / 100)) for k, v in present.items()}
                diff = (100 - take) - sum(scaled.values())
                if diff and scaled:
                    top = max(scaled, key=lambda k: scaled[k])
                    scaled[top] += diff
                raw.update(scaled)
                raw["company"] = take
            else:
                raw.setdefault("company", 15)
                raw.setdefault("management", 15)
        return raw

    @model_validator(mode="after")
    def weights_sum_to_100(self) -> Self:
        total = self.total()
        if total != 100:
            raise ValueError(f"сумма весов должна быть 100, получено {total}")
        return self


class FixedScoringWeights(BaseModel):
    """Веса salary/management, не настраиваемые в UI «Резюме».

    Источник правды — константы `core.domains.opportunities.score_breakdown`; отдаём их сюда,
    чтобы фронт не дублировал числа локальной константой, которая может разъехаться с формулой.
    """

    salary: int
    management: int


class CompanyAdjustment(BaseModel):
    """Одна строка калибровки компаний (подстроки OR + дельта + опциональный cap)."""

    match: list[str] = Field(min_length=1)
    delta: int
    reason: str = ""
    cap: float | None = Field(default=None, gt=0, le=1)

    @model_validator(mode="after")
    def normalize_match(self) -> Self:
        cleaned = [m.strip() for m in self.match if m.strip()]
        if not cleaned:
            raise ValueError("match должен содержать хотя бы одну непустую подстроку")
        self.match = cleaned
        return self


class DisclosurePolicy(BaseModel):
    """Что скрывать в исходящих письмах под международный рынок (`app_settings.disclosure_policy`,
    Э4.2). Дефолт — скрыть только текущее место работы."""

    hide_current_employer: bool = True
    hide_all_employers: bool = False
    hide_public_links: bool = True
    coarse_dates: bool = False
    coarse_city: bool = False


class AppSettingsResponse(BaseModel):
    """Текущие параметры; секрет OpenRouter не отдаётся — только флаг наличия."""

    scoring_weights: ScoringWeights
    scoring_importance: ScoringImportance
    fixed_scoring_weights: FixedScoringWeights
    # power-user, только API: веб-UI нет (см. CLAUDE.md → Runtime settings).
    company_adjustments: list[CompanyAdjustment]
    salary_min_override: int | None = None
    openrouter_key_configured: bool = False
    # Когда ключ OpenRouter был сохранён/обновлён последний раз — для подписи «дата вставки
    # токена» в блоке OpenRouter на «Аккаунте». Ключа нет → None.
    openrouter_key_set_at: datetime | None = None
    # Кто поставил действующий ключ: 'self' — сам человек, 'admin' — оператор из админ-панели
    # (такой ключ не показываем и сбросить его нельзя). Ключа нет → None.
    openrouter_key_origin: Literal["self", "admin"] | None = None
    # Статус последней заявки на ключ (pending/approved/rejected/fulfilled) — по нему «Аккаунт»
    # показывает «заявка в работе» вместо повторной кнопки. Заявок не было → None.
    openrouter_key_request_status: str | None = None
    # AUTH-1: онбординг — пользователь отметил «Расширение установлено» (не блокирует).
    extension_confirmed: bool = False
    # TB-2.4: пуши бота (дайджест / прогрев / стиль карточки / уборка батча).
    telegram_prefs: TelegramPrefs = Field(default_factory=TelegramPrefs)
    # Автоотклики (hh/getmatch/habr) — настраиваются в «Расширении», выключено по умолчанию.
    auto_apply_config: AutoApplyConfig = Field(default_factory=AutoApplyConfig)
    # Discovery (авто-открытие вакансий фоновыми вкладками) — настраивается в «Расширении».
    discovery_config: DiscoveryConfig = Field(default_factory=DiscoveryConfig)
    # Э4.2 dual_employment_and_contracting_2026.md: что скрывать в исходящих письмах под
    # международный рынок (карточка «Международный профиль» в «Резюме»).
    disclosure_policy: DisclosurePolicy = Field(default_factory=DisclosurePolicy)


class OpenRouterKeyRequestResponse(BaseModel):
    """Ответ на «Запросить ключ»: что случилось и что показать человеку."""

    status: Literal["created", "already_pending", "already_has_key"]
    message: str


class AppSettingsUpdate(BaseModel):
    """PATCH-семантика: поле отсутствует в теле → не менять; `null` → сбросить override."""

    scoring_weights: ScoringWeights | None = None
    scoring_importance: ScoringImportance | None = None
    company_adjustments: list[CompanyAdjustment] | None = None
    salary_min_override: int | None = Field(default=None, ge=0)
    openrouter_api_key: str | None = None
    extension_confirmed: bool | None = None
    telegram_prefs: TelegramPrefs | None = None
    auto_apply_config: AutoApplyConfig | None = None
    discovery_config: DiscoveryConfig | None = None
    disclosure_policy: DisclosurePolicy | None = None


# --- Чат по резюме (вкладка «Резюме», под ResumeScoreCard) ---
# Лента реплик user/assistant аккаунта. Персист на бэкенде (resume_chat_messages): история
# переживает переход между разделами и перезагрузку.


class ResumeChatMessageOut(BaseModel):
    """Реплика чата по резюме. role: user (владелец) | assistant (LLM).

    `reply_to_message_id`/`attachments` (паритет с чатом «Рынка», миграция 0120) — раньше
    композер был упрощённым (только текст), теперь отвечает/вкладывает как чат по рынку."""

    id: int
    role: Literal["user", "assistant"]
    content: str
    reply_to_message_id: int | None = None
    attachments: list[AttachmentOut] = Field(default_factory=list)
    created_at: datetime | None = None


class ResumeChatHistory(BaseModel):
    """История чата по резюме аккаунта запроса (хронологически). Нет PG → пустой список."""

    items: list[ResumeChatMessageOut] = Field(default_factory=list)


# --- GM-13: расхождения getmatch-профиля vs Copilot-резюме ---


class GmProfileIngest(BaseModel):
    """Приём getmatch-профиля из расширения (GET /api/profiles → парсер → сюда).

    Сырой контракт расширения; доменная модель `core.domains.profile.gm_profile.GmProfile`
    валидирует/сравнивает. `profile` — объект профиля getmatch в том виде, как его распарсил
    content-script.
    """

    profile: dict[str, Any] = Field(default_factory=dict)


class GmProfileDiscrepancyOut(BaseModel):
    """Одно расхождение getmatch ↔ Copilot (для подсветки на вкладке «Резюме»)."""

    field: str = ""
    label: str = ""
    getmatch: str = ""
    copilot: str = ""


class GmProfileDiffResponse(BaseModel):
    """Результат сравнения последнего снимка getmatch с Copilot-резюме.

    `available` — снимок getmatch вообще приходил (иначе нечего сравнивать);
    `discrepancies` — список расхождений; `stored` — приём снимка сохранил его (нет PG →
    false, но diff всё равно вернётся из только что присланного профиля).
    """

    available: bool = False
    stored: bool = False
    discrepancies: list[GmProfileDiscrepancyOut] = Field(default_factory=list)


# --- GM-12: мониторинг заполненности профиля getmatch (/api/trust) ---


class GmTrustIngest(BaseModel):
    """Приём чеклиста доверия getmatch из расширения (GET /api/trust → парсер → сюда).

    Сырой контракт расширения; доменная модель `core.domains.profile.gm_trust.GmTrust`
    валидирует/считает. `trust` — объект чеклиста в том виде, как его распарсил content-script.
    """

    trust: dict[str, Any] = Field(default_factory=dict)


class GmTrustStatusOut(BaseModel):
    """Состояние заполненности профиля getmatch (для плашки на вкладке «Резюме»).

    `filled_count`/`total_checks` — «заполнен на N/6»; `missing_checks` — конкретные пропуски
    из чеклиста (фото, навыки, …); `missing_connections` — неподключённые внешние профили.
    """

    available: bool = False
    trusted: bool = False
    profile_filled: bool = False
    filled_count: int = 0
    total_checks: int = 6
    missing_checks: list[str] = Field(default_factory=list)
    missing_connections: list[str] = Field(default_factory=list)


class GmTrustIngestResponse(BaseModel):
    """Результат приёма чеклиста доверия. `stored=false` — нет PG (статус всё равно вернётся)."""

    stored: bool = False
    status: GmTrustStatusOut = Field(default_factory=GmTrustStatusOut)


__all__ = [
    "SearchProfileSuggestRequest",
    "PrioritySuggestionOut",
    "SearchProfileSuggestResponse",
    "ResumeStatsIngest",
    "ResumeStatsIngestResponse",
    "ResumeViewRow",
    "ResumeViewsIngest",
    "ResumeViewsIngestResponse",
    "ResumeStatPoint",
    "ResumeStatsSeries",
    "ScoringImportance",
    "ScoringWeights",
    "FixedScoringWeights",
    "CompanyAdjustment",
    "AppSettingsResponse",
    "AppSettingsUpdate",
    "ResumeChatMessageOut",
    "ResumeChatHistory",
    "GmProfileIngest",
    "GmProfileDiscrepancyOut",
    "GmProfileDiffResponse",
    "GmTrustIngest",
    "GmTrustStatusOut",
    "GmTrustIngestResponse",
]
