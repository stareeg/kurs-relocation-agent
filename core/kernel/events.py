"""Доменные события: факт, случившийся в домене, без знания о том, кто его слушает.

Событие — прошедшее время и минимум данных для реакции: идентификаторы плюс пара полей, по
которым подписчик решает, нужно ли ему грузить остальное. Тяжёлые модели (`ScoreResult`,
`VacancySelfPres`) в событие не кладём — подписчик достанет их репозиторием своего домена,
иначе шина тихо превращается в транспорт между доменами и связывает их сильнее, чем прямой
вызов, который она заменила.

Публикация — только через порт `core.kernel.ports.events()`. Диспетчер (`InProcessEventBus`)
живёт там же; журнал витрины (`copilot_logs`) подключается композиционным корнем из
`core/platform/events/journal.py` — слой `kernel` про него не знает.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from dataclasses import fields as dataclass_fields
from datetime import UTC, datetime
from typing import Any

from core.kernel.ids import OfferId, VacancyId

#: Служебные поля базы — в журнал попадают отдельно, не как поля события.
_BASE_FIELDS = frozenset({"occurred_at", "payload"})


@dataclass(frozen=True, slots=True)
class DomainEvent:
    """Базовый маркер доменного события.

    `payload` — свободный довесок для редких случаев, когда подписчику нужна деталь, ради
    которой не стоит заводить поле. Регулярные данные заводятся полями наследника.
    """

    occurred_at: datetime = field(default_factory=lambda: datetime.now(UTC))
    payload: dict[str, Any] = field(default_factory=dict)

    @property
    def name(self) -> str:
        """Имя события для журнала и метрик."""
        return type(self).__name__

    @property
    def subject(self) -> str:
        """К чему относится событие — ключ корреляции строк витрины (обычно `vacancy_id`)."""
        return ""

    def to_fields(self) -> dict[str, Any]:
        """Плоские поля для журнала (`copilot_logs.fields`); пустые значения не пишем."""
        data = {
            f.name: getattr(self, f.name)
            for f in dataclass_fields(self)
            if f.name not in _BASE_FIELDS
        }
        result = {k: v for k, v in data.items() if v is not None and v != ""}
        if self.payload:
            result["payload"] = self.payload
        return result


@dataclass(frozen=True, slots=True)
class VacancyScored(DomainEvent):
    """Вакансия оценена и записана в `jobs` (`opportunities.persist_scored`)."""

    vacancy_id: VacancyId = VacancyId("")
    job_id: int | None = None
    overall_score: float | None = None
    recommendation: str = ""
    source: str = ""
    # Этап 3 (account_id retrofit): подписчики (on_vacancy_scored → get_job_by_vacancy_id) сами
    # требуют account_id — без него не знали бы, чью jobs-строку читать после multi-account.
    account_id: int = 0

    @property
    def subject(self) -> str:
        return self.vacancy_id


@dataclass(frozen=True, slots=True)
class ApplicationStageChanged(DomainEvent):
    """Вакансия сменила стадию воронки (`opportunities.add_stage` — единственная точка записи)."""

    vacancy_id: VacancyId = VacancyId("")
    job_id: int | None = None
    stage: str = ""
    previous_stage: str = ""
    source: str = ""
    account_id: int = 0

    @property
    def subject(self) -> str:
        return self.vacancy_id or (str(self.job_id) if self.job_id else "")


@dataclass(frozen=True, slots=True)
class HrMessageReceived(DomainEvent):
    """Разобрана пачка HR-переписки (`pipeline.process_hr_batch`)."""

    vacancy_id: VacancyId = VacancyId("")
    thread_id: str = ""
    intent: str = ""
    funnel_status: str = ""
    channel: str = ""
    account_id: int = 0

    @property
    def subject(self) -> str:
        return self.vacancy_id or self.thread_id


@dataclass(frozen=True, slots=True)
class ScreeningPackReady(DomainEvent):
    """Собран пакет самопрезентации к скринингу (`preparation.generate_self_pres_pack`)."""

    vacancy_id: VacancyId = VacancyId("")
    company: str = ""
    pitch_blocks: int = 0
    hr_questions: int = 0

    @property
    def subject(self) -> str:
        return self.vacancy_id


@dataclass(frozen=True, slots=True)
class InterviewDebriefed(DomainEvent):
    """Разбор собеседования сохранён (`preparation.save_debrief`)."""

    vacancy_id: VacancyId = VacancyId("")
    stage: str = ""
    signal: str = ""
    debrief_id: int | None = None
    # M3 (account_id retrofit): подписчики (career.facts.record_facts_from_debrief →
    # preparation.debrief.get_debrief/load_debrief_history) сами требуют account_id.
    account_id: int = 0

    @property
    def subject(self) -> str:
        return self.vacancy_id


@dataclass(frozen=True, slots=True)
class OfferReceived(DomainEvent):
    """Появился новый оффер (`offers.upsert_offer`, первая запись по вакансии).

    Оффер в этой системе уникален по вакансии, поэтому `offer_id == vacancy_id`; отдельное поле
    оставлено, чтобы подписчики не завязывались на это совпадение.
    """

    offer_id: OfferId = OfferId("")
    vacancy_id: VacancyId = VacancyId("")
    company: str = ""
    status: str = ""
    # M5 (plans/multitenancy_gaps_2026_08_06.md §3.7): career_timeline требует account_id —
    # подписчик (career.events.on_offer_received) без него не знал бы, чью ленту писать.
    account_id: int = 0

    @property
    def subject(self) -> str:
        return self.vacancy_id or self.offer_id


@dataclass(frozen=True, slots=True)
class ResumeUpdated(DomainEvent):
    """Резюме сохранено (`profile.save_resume_data`) — скоринг и профиль поиска поедут следом."""

    source: str = ""
    # M1 (plans/multitenancy_gaps_2026_08_06.md §3.1): подписчик (on_resume_updated →
    # maybe_auto_refresh_for_resume_change) требует account_id — без него не знал бы, чей снимок
    # навыков пересобирать. 0 — bootstrap-путь (account_id=None у save_resume_data), подписчик
    # его пропускает.
    account_id: int = 0


@dataclass(frozen=True, slots=True)
class SearchModeChanged(DomainEvent):
    """Переключён режим поиска (`career.search_state.set_search_mode`).

    `subject` — сам режим: событие глобально, корреляции с вакансией у него нет.
    """

    mode: str = ""
    prev_mode: str = ""
    actor: str = ""
    reason: str = ""
    # M5 (plans/multitenancy_gaps_2026_08_06.md §3.7): search_state_log/career_timeline требуют
    # account_id — режим поиска больше не глобальный, а личный для каждого аккаунта.
    account_id: int = 0

    @property
    def subject(self) -> str:
        return self.mode


@dataclass(frozen=True, slots=True)
class SearchTrackChanged(DomainEvent):
    """Изменён набор треков поиска (`career.track_state.set_tracks`)."""

    tracks: tuple[str, ...] = ()
    prev_tracks: tuple[str, ...] = ()
    actor: str = ""
    reason: str = ""
    account_id: int = 0

    @property
    def subject(self) -> str:
        return ",".join(self.tracks)


@dataclass(frozen=True, slots=True)
class AttachmentAnalyzed(DomainEvent):
    """Вложение-картинка распознано фоном (`assistant.attachments.tasks`).

    `subject` — id вложения, а не `vacancy_id`: распознавание стартует на upload, когда
    картинка ещё ни к какому сообщению не привязана и вакансия неизвестна.
    """

    attachment_id: int = 0
    kind: str = ""

    @property
    def subject(self) -> str:
        return str(self.attachment_id) if self.attachment_id else ""


@dataclass(frozen=True, slots=True)
class VacancyDeduplicated(DomainEvent):
    """Одна и та же вакансия найдена на другой площадке (дедупликация `opportunities.dedup`).

    Не создаём новую строку `jobs` — прикрепляем ссылку к канонической и дозаполняем пустые
    поля. `vacancy_id` — входящий (новый) площадочный id; `canonical_job_id` — строка `jobs`,
    к которой прикреплена ссылка; `enriched` — какие поля канона дозаполнены.
    """

    vacancy_id: VacancyId = VacancyId("")
    canonical_job_id: int | None = None
    source: str = ""
    enriched: dict[str, Any] = field(default_factory=dict)
    account_id: int = 0

    @property
    def subject(self) -> str:
        return self.vacancy_id or (str(self.canonical_job_id) if self.canonical_job_id else "")


#: События первой очереди: по этому списку сверяются декларации доменов и тесты.
FIRST_ORDER_EVENTS: tuple[type[DomainEvent], ...] = (
    VacancyScored,
    ApplicationStageChanged,
    HrMessageReceived,
    ScreeningPackReady,
    InterviewDebriefed,
    OfferReceived,
    ResumeUpdated,
    SearchModeChanged,
    SearchTrackChanged,
    AttachmentAnalyzed,
    VacancyDeduplicated,
)


__all__ = [
    "FIRST_ORDER_EVENTS",
    "ApplicationStageChanged",
    "AttachmentAnalyzed",
    "DomainEvent",
    "HrMessageReceived",
    "InterviewDebriefed",
    "OfferReceived",
    "ResumeUpdated",
    "ScreeningPackReady",
    "SearchModeChanged",
    "SearchTrackChanged",
    "VacancyDeduplicated",
    "VacancyScored",
]
