"""Repository переписок с HR по вакансии: треды + сообщения in/out.

По образцу `core.domains.preparation.debrief`/`core.domains.offers.store`: свои Pydantic-модели, без зависимости от
api/bot. Диалог с HR часто уходит из hh в Telegram — ведём его в системе и привязываем к вакансии,
чтобы по десяткам параллельных процессов не теряться (CLAUDE.md).

Тред — `hr_threads` (контакт/канал/статус по вакансии); сообщения — `hr_messages` (in/out, лента по
времени). `message_count`/`last_message_at` в списке тредов считаются join'ом (дешёвый список без
догрузки сообщений). Списки сортируются по `last_message_at` (реальное время последнего сообщения),
а не по `updated_at` треда — последнее бампается и метаданными (статус/имя HR), не только
сообщениями, и не годится для сортировки.
"""

from __future__ import annotations

from collections.abc import Sequence
from datetime import UTC, datetime
from typing import Any

from pydantic import BaseModel, model_validator

from core.platform.db.pool import Executor, get_pool, row_to_dict

_THREAD_COLS = (
    "id, vacancy_id, contact_name, channel, company, status, pinned, created_at, updated_at, "
    "suggested_funnel_status, suggested_stage_type, suggestion_source_message_id"
)
_MESSAGE_COLS = (
    "id, thread_id, direction, kind, body, sent_at, created_at, author_uncertain, "
    "reply_to_message_id"
)

# Тип реплики → бинарный direction (out = написал владелец, in = владелец получил).
# kind авторитетнее direction; direction держим согласованным ради старых выборок/CHECK.
_DIRECTION_FOR_KIND = {
    "hr_in": "in",
    "hr_out": "out",
    "llm_user": "out",
    "llm_assistant": "in",
}
# Реплики реальной переписки с HR (кормятся в извлечение фактов); llm_* — болтовня с ассистентом.
HR_KINDS = ("hr_in", "hr_out")

# Список/карточка треда с денорм-агрегатами (число сообщений, время последнего, направление и время
# последней РЕАЛЬНОЙ hr-реплики — RD-13 радар «ждёт меня / ждём их», скалярные подзапросы вместо
# GROUP BY, чтобы не тащить функциональную зависимость через лишний join). next_stage_* —
# ближайший назначенный этап `interview_stages` этой вакансии, для бейджа «Созвон: чт 15:00» в
# шапке диалога и сайдбаре Чатов; событие извлекается фоном из HR-переписки
# (core.hr.event_extract). suggested_* — предложение сдвига воронки из диалога.
_THREAD_SELECT = (
    "select t.id, t.vacancy_id, t.contact_name, t.channel, t.company, t.status, t.pinned, "
    "t.created_at, t.updated_at, "
    "t.suggested_funnel_status, t.suggested_stage_type, t.suggestion_source_message_id, "
    "(select count(*) from hr_messages hm where hm.thread_id = t.id) as message_count, "
    "(select max(hm.sent_at) from hr_messages hm where hm.thread_id = t.id) as last_message_at, "
    "lhr.kind as last_hr_kind, lhr.sent_at as last_hr_at, "
    "nstg.stage_type as next_stage_type, nstg.scheduled_at as next_stage_at "
    "from hr_threads t "
    "left join lateral ("
    "  select kind, sent_at from hr_messages "
    "  where thread_id = t.id and kind in ('hr_in', 'hr_out') "
    "  order by sent_at desc, id desc limit 1"
    ") lhr on true "
    "left join lateral ("
    "  select stage_type, scheduled_at from interview_stages "
    "  where vacancy_id = t.vacancy_id and status = 'scheduled' and scheduled_at is not null "
    "  order by scheduled_at asc limit 1"
    ") nstg on true"
)


def _now() -> datetime:
    return datetime.now(UTC)


def _aware(dt: datetime | None) -> datetime | None:
    """Naive datetime → UTC-aware (timestamptz). PG-времена уже aware, ручные — могут быть naive."""
    if dt is None:
        return None
    return dt if dt.tzinfo is not None else dt.replace(tzinfo=UTC)


class HrThread(BaseModel):
    """Разговор по вакансии (HR-переписка + уточняющий LLM-чат). CHECK — в миграциях 0019/0020/0036.

    channel: telegram | hh | getmatch | email | phone | other
        'getmatch' — тег происхождения: контакты выданы на getmatch.ru, но сам диалог идёт
        во внешнем канале (на getmatch нет чата с HR).
    status:  active | waiting | closed | archived
    pinned — закреплён в списке «Диалоги» слева (кнопка-булавка, независимо от статуса/архива).
    last_hr_kind/last_hr_at — направление и время последней РЕАЛЬНОЙ hr-реплики
        (hr_in/hr_out, без llm_* болтовни): hr_in → тред ждёт ответа владельца, hr_out →
        ждём ответа HR. None — реальной переписки в треде ещё не было.
    next_stage_type/next_stage_at — ближайший назначенный этап `interview_stages` этой
        вакансии (созвон/собес с известной датой). None — этап не назначен/не извлечён.
    suggested_* — предложение сдвинуть воронку по сигналу из HR-диалога (чип в шапке).
        None — предложения нет / снято / уже не актуально.
    """

    id: int | None = None
    vacancy_id: str
    contact_name: str = ""
    channel: str = "telegram"
    company: str = ""
    status: str = "active"
    pinned: bool = False
    message_count: int = 0
    last_message_at: datetime | None = None
    last_hr_kind: str | None = None
    last_hr_at: datetime | None = None
    next_stage_type: str | None = None
    next_stage_at: datetime | None = None
    suggested_funnel_status: str | None = None
    suggested_stage_type: str | None = None
    suggestion_source_message_id: int | None = None
    created_at: datetime | None = None
    updated_at: datetime | None = None


class HrMessage(BaseModel):
    """Реплика разговора. `kind`: hr_in | hr_out | llm_user | llm_assistant — авторитетен.

    direction оставлен для совместимости/выборок (out = автор владелец, in = владелец получил);
    выводится из kind. kind=None у вызывающего → берём из direction (старые вызовы in/out).

    author_uncertain — LLM-разбор дампа не уверен в авторе; funnel_suggest такие hr_in
    пропускает, UI помечает реплику.

    reply_to_message_id — реплика, на которую отвечает эта (composer «Ответить»): у llm_user несёт
    id сообщения-источника, prompt LLM получает его текст цитатой (core.domains.assistant.service).
    """

    id: int | None = None
    thread_id: int
    direction: str = "in"
    kind: str | None = None
    body: str = ""
    sent_at: datetime | None = None
    created_at: datetime | None = None
    author_uncertain: bool = False
    reply_to_message_id: int | None = None

    @model_validator(mode="after")
    def _sync_kind_direction(self) -> HrMessage:
        """kind ↔ direction всегда согласованы: kind задан → direction из него; иначе kind из direction.

        kind после конструирования всегда непустой (старые вызовы с одним direction in/out получают
        hr_in/hr_out), поэтому проекция в API-схему не падает на None.
        """
        if self.kind is None:
            self.kind = "hr_out" if self.direction == "out" else "hr_in"
        else:
            self.direction = _DIRECTION_FOR_KIND.get(self.kind, self.direction)
        return self


async def save_thread(thread: HrThread, *, account_id: int, db: Executor | None = None) -> HrThread:
    """Создать тред под вакансию. Возвращает с id и временами (message_count=0)."""
    if not thread.vacancy_id:
        raise ValueError("vacancy_id required")
    db = db or get_pool()
    row = await db.fetchrow(
        "insert into hr_threads (vacancy_id, contact_name, channel, company, status, account_id) "
        "values ($1, $2, $3, $4, $5, $6) "
        f"returning {_THREAD_COLS}",
        thread.vacancy_id,
        thread.contact_name,
        thread.channel,
        thread.company,
        thread.status,
        account_id,
    )
    assert row is not None  # insert ... returning всегда отдаёт строку
    return HrThread(**row_to_dict(row))


async def list_threads_by_vacancy(
    vacancy_id: str, *, account_id: int, db: Executor | None = None
) -> list[HrThread]:
    """Треды по вакансии (свежие сверху) + число сообщений и время последнего."""
    db = db or get_pool()
    rows = await db.fetch(
        f"{_THREAD_SELECT} where t.vacancy_id = $1 and t.account_id = $2 "
        "order by last_message_at desc nulls last, t.created_at desc",
        vacancy_id,
        account_id,
    )
    return [HrThread(**row_to_dict(r)) for r in rows]


async def get_thread(
    thread_id: int, *, account_id: int, db: Executor | None = None
) -> HrThread | None:
    """Один тред с агрегатами (после смены статуса/добавления сообщения). None — треда нет."""
    db = db or get_pool()
    row = await db.fetchrow(
        f"{_THREAD_SELECT} where t.id = $1 and t.account_id = $2", thread_id, account_id
    )
    return HrThread(**row_to_dict(row)) if row else None


async def update_thread(
    thread_id: int,
    *,
    status: str | None = None,
    contact_name: str | None = None,
    channel: str | None = None,
    company: str | None = None,
    pinned: bool | None = None,
    account_id: int,
    db: Executor | None = None,
) -> HrThread | None:
    """Правка треда (статус/контакт/канал/компания/закреп). None-поля не трогаем. None на выходе
    — треда нет."""
    db = db or get_pool()
    sets: list[str] = []
    params: list[Any] = []
    for col, val in (
        ("status", status),
        ("contact_name", contact_name),
        ("channel", channel),
        ("company", company),
        ("pinned", pinned),
    ):
        if val is not None:
            params.append(val)
            sets.append(f"{col} = ${len(params)}")
    if not sets:  # нечего менять — отдаём текущий
        return await get_thread(thread_id, account_id=account_id, db=db)
    sets.append("updated_at = now()")
    params.append(thread_id)
    params.append(account_id)
    updated = await db.fetchrow(
        f"update hr_threads set {', '.join(sets)} "
        f"where id = ${len(params) - 1} and account_id = ${len(params)} returning id",
        *params,
    )
    if updated is None:
        return None
    return await get_thread(thread_id, account_id=account_id, db=db)


async def set_funnel_suggestion(
    thread_id: int,
    *,
    funnel_status: str,
    stage_type: str,
    source_message_id: int | None,
    account_id: int,
    db: Executor | None = None,
) -> HrThread | None:
    """Записать предложение сдвига воронки. None — треда нет."""
    db = db or get_pool()
    updated = await db.fetchrow(
        "update hr_threads set suggested_funnel_status = $1, suggested_stage_type = $2, "
        "suggestion_source_message_id = $3, updated_at = now() "
        "where id = $4 and account_id = $5 returning id",
        funnel_status,
        stage_type,
        source_message_id,
        thread_id,
        account_id,
    )
    if updated is None:
        return None
    return await get_thread(thread_id, account_id=account_id, db=db)


async def clear_funnel_suggestion(
    thread_id: int, *, account_id: int, db: Executor | None = None
) -> HrThread | None:
    """Снять предложение сдвига воронки (применить / отклонить / устарело). None — треда нет."""
    db = db or get_pool()
    updated = await db.fetchrow(
        "update hr_threads set suggested_funnel_status = null, suggested_stage_type = null, "
        "suggestion_source_message_id = null, updated_at = now() "
        "where id = $1 and account_id = $2 returning id",
        thread_id,
        account_id,
    )
    if updated is None:
        return None
    return await get_thread(thread_id, account_id=account_id, db=db)


async def delete_thread(thread_id: int, *, account_id: int, db: Executor | None = None) -> bool:
    """Удалить тред (каскадом — его сообщения). True — строка была."""
    db = db or get_pool()
    row = await db.fetchrow(
        "delete from hr_threads where id = $1 and account_id = $2 returning id",
        thread_id,
        account_id,
    )
    return row is not None


async def add_message(
    message: HrMessage, *, account_id: int, db: Executor | None = None
) -> HrMessage:
    """Добавить реплику и освежить updated_at треда (свежие сверху). kind ↔ direction согласуем."""
    db = db or get_pool()
    sent = _aware(message.sent_at) or _now()
    kind = message.kind
    if kind:
        direction = _DIRECTION_FOR_KIND.get(kind, message.direction)
    else:  # старый вызов с direction in/out — выводим kind
        kind = "hr_out" if message.direction == "out" else "hr_in"
        direction = message.direction
    row = await db.fetchrow(
        "insert into hr_messages "
        "(thread_id, direction, kind, body, sent_at, author_uncertain, reply_to_message_id, "
        "account_id) "
        "values ($1, $2, $3, $4, $5, $6, $7, $8) "
        f"returning {_MESSAGE_COLS}",
        message.thread_id,
        direction,
        kind,
        message.body,
        sent,
        bool(message.author_uncertain),
        message.reply_to_message_id,
        account_id,
    )
    assert row is not None
    await db.execute(
        "update hr_threads set updated_at = now() where id = $1 and account_id = $2",
        message.thread_id,
        account_id,
    )
    return HrMessage(**row_to_dict(row))


async def add_messages(
    messages: list[HrMessage], *, account_id: int, db: Executor | None = None
) -> list[HrMessage]:
    """Пакетная вставка реплик по порядку (импорт вставленного дампа переписки)."""
    db = db or get_pool()
    return [await add_message(m, account_id=account_id, db=db) for m in messages]


async def list_messages(
    thread_id: int, *, account_id: int, db: Executor | None = None
) -> list[HrMessage]:
    """Лента сообщений треда по времени (старые слева — хронология диалога)."""
    db = db or get_pool()
    rows = await db.fetch(
        f"select {_MESSAGE_COLS} from hr_messages where thread_id = $1 and account_id = $2 "
        "order by sent_at asc, id asc",
        thread_id,
        account_id,
    )
    return [HrMessage(**row_to_dict(r)) for r in rows]


async def get_message(
    message_id: int, *, account_id: int, db: Executor | None = None
) -> HrMessage | None:
    """Одна реплика по id — цитата в промпте LLM при ответе на сообщение (composer «Ответить»)."""
    db = db or get_pool()
    row = await db.fetchrow(
        f"select {_MESSAGE_COLS} from hr_messages where id = $1 and account_id = $2",
        message_id,
        account_id,
    )
    return HrMessage(**row_to_dict(row)) if row else None


async def delete_message(message_id: int, *, account_id: int, db: Executor | None = None) -> bool:
    """Удалить одну реплику ленты (выделение → Удалить во фронте). True — строка была."""
    db = db or get_pool()
    row = await db.fetchrow(
        "delete from hr_messages where id = $1 and account_id = $2 returning id",
        message_id,
        account_id,
    )
    return row is not None


async def archive_threads_for_vacancy(
    vacancy_id: str, *, account_id: int, db: Executor | None = None
) -> int:
    """Пометить все треды вакансии как archived (Отказ/Пропуск на доске → диалог в архив Чатов)."""
    vid = (vacancy_id or "").strip()
    if not vid:
        return 0
    db = db or get_pool()
    result = await db.execute(
        "update hr_threads set status = 'archived', updated_at = now() "
        "where vacancy_id = $1 and account_id = $2 and status <> 'archived'",
        vid,
        account_id,
    )
    try:
        return int(str(result).split()[-1])
    except (ValueError, IndexError):
        return 0


async def unarchive_threads_for_vacancy(
    vacancy_id: str, *, account_id: int, db: Executor | None = None
) -> int:
    """Воронка вернулась в активную стадию → вернуть архивные треды вакансии в active.

    Симметрично `archive_threads_for_vacancy`: до этого возврата не было вовсе — тред,
    заархивированный авто-отказом hh.ru-синка, оставался `status='archived'` навсегда, даже
    когда владелец вручную возвращал воронку обратно (job 317, «ТехВилл», 2026-08-12)."""
    vid = (vacancy_id or "").strip()
    if not vid:
        return 0
    db = db or get_pool()
    result = await db.execute(
        "update hr_threads set status = 'active', updated_at = now() "
        "where vacancy_id = $1 and account_id = $2 and status = 'archived'",
        vid,
        account_id,
    )
    try:
        return int(str(result).split()[-1])
    except (ValueError, IndexError):
        return 0


async def list_recent_threads(
    *,
    include_archived: bool = False,
    limit: int = 200,
    account_id: int,
    db: Executor | None = None,
) -> list[HrThread]:
    """Все разговоры (по всем вакансиям), закреплённые и свежие сверху — для хаба слева."""
    db = db or get_pool()
    status_clause = "" if include_archived else "and t.status <> 'archived'"
    rows = await db.fetch(
        f"{_THREAD_SELECT} where t.account_id = $2 {status_clause} "
        "order by t.pinned desc, last_message_at desc nulls last, t.created_at desc limit $1",
        limit,
        account_id,
    )
    return [HrThread(**row_to_dict(r)) for r in rows]


async def list_archived_vacancy_ids(*, account_id: int, db: Executor | None = None) -> set[str]:
    """vacancy_id диалогов в архиве Чатов.

    Витрина «Сегодня» читает этапы и сильные вакансии отдельно от тредов — без этого списка
    напоминалка всплывала бы по вакансии, чей чат уже убрали из активного списка.
    """
    db = db or get_pool()
    rows = await db.fetch(
        "select vacancy_id from hr_threads "
        "where account_id = $1 and status = 'archived' and vacancy_id is not null",
        account_id,
    )
    return {str(r["vacancy_id"]) for r in rows if r["vacancy_id"]}


async def count_active_threads(*, account_id: int, db: Executor | None = None) -> int:
    """Число «живых» разговоров для бейджа в сайдбаре рядом с «Чаты».

    Раньше считали всё, что не в архиве (`status <> 'archived'`) — но тред остаётся `active`,
    пока его вакансия не ушла в «Отказ»/«Пропущено» и авто-архив не сработал (или не сработал
    вовсе). Такие треды — мёртвый процесс, в сайдбаре их не должно быть. Определение «живого»
    совпадает с `opportunities.jobs.count_active_jobs`: engaged-статус воронки (Отклик/Скрининг/
    Техничка/Финал/Оффер) или «Просмотр» с реальной перепиской, и вакансия не пропущена.
    """
    from core.kernel.schemas.funnel import ENGAGED_FUNNEL_STATUSES, FunnelStatus

    engaged = sorted(ENGAGED_FUNNEL_STATUSES)
    db = db or get_pool()
    row = await db.fetchrow(
        "select count(*) as n from hr_threads t "
        "where t.account_id = $3 and t.status <> 'archived' "
        "and not exists("
        "  select 1 from skipped_vacancies sv "
        "  where sv.account_id = t.account_id and sv.vacancy_id = t.vacancy_id"
        ") "
        "and exists("
        "  select 1 from jobs j "
        "  where j.account_id = t.account_id and j.vacancy_id = t.vacancy_id "
        "  and ("
        "    j.status = any($1::text[]) "
        "    or ("
        "      coalesce(nullif(trim(j.status), ''), $2) in ($2, 'Просмотрено') "
        "      and exists(select 1 from hr_messages hm where hm.thread_id = t.id)"
        "    )"
        "  )"
        ")",
        engaged,
        FunnelStatus.VIEWED.value,
        account_id,
    )
    assert row is not None
    return int(row["n"])


async def count_threads_active_in_period(
    *,
    account_id: int,
    period_start: datetime,
    period_end: datetime,
    db: Executor | None = None,
) -> int:
    """Число диалогов (тредов) с хотя бы одним сообщением в окне — «Диалоги» шкалы периода
    «Рынка» (не архивный статус треда, а реальная активность: любой `hr_in`/`hr_out`/
    `llm_user`/`llm_assistant` в окне, включая архивные треды, если в них писали в период)."""
    db = db or get_pool()
    row = await db.fetchrow(
        "select count(distinct thread_id) as n from hr_messages hm "
        "join hr_threads t on t.id = hm.thread_id "
        "where t.account_id = $1 and hm.sent_at >= $2 and hm.sent_at <= $3",
        account_id,
        period_start,
        period_end,
    )
    assert row is not None
    return int(row["n"])


async def chat_velocity_signals(
    *,
    account_id: int,
    period_start: datetime,
    period_end: datetime,
    stall_days: int = 10,
    db: Executor | None = None,
) -> tuple[int, int, int]:
    """Сигналы скорости Чатов для фактора «Общение» композита «Шанс офферов» (правка 2026-08-14).

    Возвращает кортеж `(active, stalled, progressing)`:
    * `active` — тредов с хотя бы одним сообщением в окне (как `count_threads_active_in_period`,
      но одним запросом вместе с остальными сигналами, без дублей).
    * `stalled` — из активных тредов те, где последняя РЕАЛЬНАЯ hr-реплика (`hr_in`/`hr_out`)
      от HR (`hr_in`) и старше `stall_days` дней — «HR ответил, ждём кандидата, и давно», либо
      последняя реплика от кандидата (`hr_out`) и ответа HR нет дольше `stall_days` —
      «кандидат ответил, HR пропал». Оба случая = процесс завис.
    * `progressing` — из активных тредов те, где за период сменился этап воронки
      (`application_stages.changed_at` в окне по `vacancy_id` треда) — процесс двигается.

    `hr_threads`/`hr_messages` привязаны к `vacancy_id`, как и `application_stages` — join по
    вакансии даёт «двигался ли этап в диалоге». Без PG / нет таблиц → `(0, 0, 0)` (фактор
    зануляется через `has_data`, не роняет пульс).
    """
    db = db or get_pool()
    try:
        row = await db.fetchrow(
            """
            with active_threads as (
                select distinct t.id as thread_id, t.vacancy_id
                from hr_threads t
                join hr_messages hm on hm.thread_id = t.id
                where t.account_id = $1
                  and hm.sent_at >= $2 and hm.sent_at <= $3
            ),
            last_hr_kind as (
                select t.thread_id, lm.kind, lm.sent_at
                from active_threads t
                left join lateral (
                    select kind, sent_at
                    from hr_messages
                    where thread_id = t.thread_id and kind in ('hr_in', 'hr_out')
                    order by sent_at desc, id desc limit 1
                ) lm on true
            ),
            progressing as (
                select distinct t.thread_id
                from active_threads t
                join application_stages ast
                    on ast.account_id = $1
                    and exists (
                        select 1 from jobs j
                        where j.vacancy_id = t.vacancy_id and j.account_id = $1 and j.id = ast.job_id
                    )
                where ast.changed_at >= $2 and ast.changed_at <= $3
            )
            select
                count(*) as active,
                count(*) filter (
                    where lh.kind is not null
                      and lh.sent_at is not null
                      and lh.sent_at <= now() - make_interval(days => $4)
                ) as stalled,
                count(*) filter (where p.thread_id is not null) as progressing
            from active_threads t
            left join last_hr_kind lh on lh.thread_id = t.thread_id
            left join progressing p on p.thread_id = t.thread_id
            """,
            account_id,
            period_start,
            period_end,
            stall_days,
        )
    except Exception:  # noqa: BLE001 — нет PG/таблиц → нули, не роняем пульс
        return (0, 0, 0)
    if row is None:
        return (0, 0, 0)
    return (
        int(row["active"] or 0),
        int(row["stalled"] or 0),
        int(row["progressing"] or 0),
    )


async def _primary_thread_id(vacancy_id: str, *, account_id: int, db: Executor) -> int | None:
    """ID канонического разговора вакансии: открытый приоритетнее закрытого/архивного, затем старейший.

    Так LLM-чат и HR-переписка по одной вакансии всегда падают в ОДИН тред (не плодим чаты из
    разных источников — карточка веба / расширение).
    """
    row = await db.fetchrow(
        "select id from hr_threads where vacancy_id = $1 and account_id = $2 "
        "order by case when status in ('closed', 'archived') then 1 else 0 end, created_at asc "
        "limit 1",
        vacancy_id,
        account_id,
    )
    return int(row["id"]) if row else None


async def get_primary_thread(
    vacancy_id: str, *, account_id: int, db: Executor | None = None
) -> HrThread | None:
    """Канонический разговор вакансии без создания (для чтения дровера). None — разговора ещё нет."""
    db = db or get_pool()
    tid = await _primary_thread_id(vacancy_id, account_id=account_id, db=db)
    return await get_thread(tid, account_id=account_id, db=db) if tid is not None else None


# Терминальные статусы воронки (как в `core.repo.enrichment`) - нет смысла пинговать про ответ HR
# на вакансии, которая уже мертва.
_DEAD_FUNNEL_STATUSES = ("Отказ", "Оффер", "Архив")


class UnansweredThread(BaseModel):
    """Тред, где последняя РЕАЛЬНАЯ реплика (hr_in/hr_out, не llm_*) - от HR, владелец не ответил.

    hh.ru отмечает кандидатов, которые быстро отвечают на приглашения работодателей, видимой
    меткой «Часто отвечает» - она напрямую поднимает резюме в поиске у рекрутера.
    """

    vacancy_id: str
    company: str = ""
    contact_name: str = ""
    last_message: str = ""
    last_message_at: datetime


async def list_unanswered_threads(
    *, hours: int = 12, limit: int = 10, account_id: int, db: Executor | None = None
) -> list[UnansweredThread]:
    """Живые треды, где последнее реальное сообщение (не llm_*) - от HR и старше `hours`.

    Используется утренним дайджестом бота - напоминание ответить HR быстро (сигнал видимости hh).
    """
    db = db or get_pool()
    rows = await db.fetch(
        """
        select t.vacancy_id, t.company, t.contact_name, m.body as last_message,
               m.sent_at as last_message_at
        from hr_threads t
        join lateral (
            select kind, body, sent_at
            from hr_messages
            where thread_id = t.id and account_id = t.account_id and kind in ('hr_in', 'hr_out')
            order by sent_at desc, id desc
            limit 1
        ) m on true
        join jobs j on j.account_id = t.account_id and j.vacancy_id = t.vacancy_id
        where t.status <> 'archived'
          and t.account_id = $4
          and m.kind = 'hr_in'
          and m.sent_at <= now() - make_interval(hours => $1)
          and (j.status is null or j.status <> all($3::text[]))
        order by m.sent_at asc
        limit $2
        """,
        hours,
        limit,
        list(_DEAD_FUNNEL_STATUSES),
        account_id,
    )
    return [UnansweredThread(**row_to_dict(r)) for r in rows]


class RecentHrContact(BaseModel):
    """Свежий HR-контакт для быстрого экрана бота: имя/линк + компания + давность."""

    vacancy_id: str
    company: str = ""
    contact_name: str = ""
    hr_link: str = ""
    last_at: datetime | None = None


async def list_recent_hr_contacts(
    *, limit: int = 8, account_id: int, db: Executor | None = None
) -> list[RecentHrContact]:
    """Последние 5–8 HR-контактов: треды + enrichment.hr_link, без пагинации (бот «на ходу»).

    Одна строка на vacancy_id (канонический тред), сортировка по последнему контакту.
    """
    lim = max(1, min(int(limit), 20))
    db = db or get_pool()
    rows = await db.fetch(
        """
        select
            t.vacancy_id,
            coalesce(nullif(t.company, ''), nullif(j.company, ''), '') as company,
            coalesce(nullif(t.contact_name, ''), '') as contact_name,
            coalesce(nullif(e.hr_link, ''), '') as hr_link,
            coalesce(
                e.last_hr_contact_at,
                (
                    select max(hm.sent_at) from hr_messages hm
                    where hm.thread_id = t.id and hm.account_id = t.account_id
                ),
                t.updated_at
            ) as last_at
        from hr_threads t
        left join vacancy_enrichment e
            on e.account_id = t.account_id and e.vacancy_id = t.vacancy_id
        left join jobs j on j.account_id = t.account_id and j.vacancy_id = t.vacancy_id
        where t.status <> 'archived'
          and t.account_id = $2
          and t.id = (
              select t2.id from hr_threads t2
              where t2.account_id = t.account_id and t2.vacancy_id = t.vacancy_id
              order by
                  case when t2.status in ('closed', 'archived') then 1 else 0 end,
                  t2.created_at asc
              limit 1
          )
        order by last_at desc nulls last
        limit $1
        """,
        lim,
        account_id,
    )
    return [RecentHrContact(**row_to_dict(r)) for r in rows]


async def format_hr_feed(
    vacancy_id: str, *, limit: int = 30, account_id: int, db: Executor | None = None
) -> str:
    """Реальная HR-лента вакансии текстом (hr_in/hr_out, без llm-болтовни), старые сверху.

    Общая точка правды для `core.domains.assistant` (лимит 30, ради длины промпта живого чата) и
    `core.domains.preparation.interview.export_context` (лимит щедрее — разовая вставка в сторонний диалог).
    """
    if not vacancy_id:
        return ""
    db = db or get_pool()
    thread = await get_primary_thread(vacancy_id, account_id=account_id, db=db)
    if thread is None or thread.id is None:
        return ""
    messages = await list_messages(thread.id, account_id=account_id, db=db)
    hr_only = [m for m in messages if m.kind in HR_KINDS and m.body.strip()]
    return "\n".join(
        f"{'HR' if m.kind == 'hr_in' else 'Я'}: {m.body.strip()}" for m in hr_only[-limit:]
    )


async def get_or_create_thread(
    vacancy_id: str,
    *,
    company: str = "",
    channel: str = "telegram",
    contact_name: str = "",
    account_id: int,
    db: Executor | None = None,
) -> HrThread:
    """Канонический разговор вакансии, создаём при отсутствии (первое сообщение/чат/импорт)."""
    if not vacancy_id:
        raise ValueError("vacancy_id required")
    db = db or get_pool()
    tid = await _primary_thread_id(vacancy_id, account_id=account_id, db=db)
    if tid is not None:
        existing = await get_thread(tid, account_id=account_id, db=db)
        if existing is not None:
            return existing
    return await save_thread(
        HrThread(
            vacancy_id=vacancy_id,
            company=company,
            channel=channel,
            contact_name=contact_name,
        ),
        account_id=account_id,
        db=db,
    )


class LlmExchangeResult(BaseModel):
    """Итог `append_llm_exchange` — тред + id только что созданных реплик.

    attachment_ids (Э2-5) привязываются к `llm_user`, поэтому вызывающему нужен именно его id —
    отсюда id обеих реплик в возврате, а не просто `HrThread`, как было раньше.
    """

    thread: HrThread
    question_message_id: int | None = None
    answer_message_id: int | None = None


async def append_llm_exchange(
    vacancy_id: str,
    *,
    question: str,
    answer: str,
    company: str = "",
    reply_to_message_id: int | None = None,
    attachment_ids: Sequence[int] = (),
    account_id: int,
    db: Executor | None = None,
) -> LlmExchangeResult:
    """Записать уточняющий обмен с ассистентом в разговор вакансии (llm_user + llm_assistant).

    Так чат по вакансии из любого источника (дровер веба / расширение) ложится в один разговор —
    видно вперемешку с реальной HR-перепиской, помечено типом реплики. reply_to_message_id —
    сообщение-источник, если вопрос задан через «Ответить» (несёт только llm_user, не ответ).
    attachment_ids — вложения текущего вопроса (Э2-5, план §2.3): связка создаётся здесь же, в
    момент персиста реплики, не раньше.
    """
    db = db or get_pool()
    thread = await get_or_create_thread(vacancy_id, company=company, account_id=account_id, db=db)
    assert thread.id is not None
    question_message_id: int | None = None
    # Картинка(и) без текста (Э2-5) — реплика всё равно нужна, иначе вложениям некуда прицепиться.
    if question.strip() or attachment_ids:
        saved = await add_message(
            HrMessage(
                thread_id=thread.id,
                kind="llm_user",
                body=question.strip(),
                reply_to_message_id=reply_to_message_id,
            ),
            account_id=account_id,
            db=db,
        )
        question_message_id = saved.id
        if attachment_ids and question_message_id is not None:
            from core.domains.assistant.attachments.service import link_to_hr_message

            await link_to_hr_message(
                question_message_id, list(attachment_ids), account_id=account_id
            )
    answer_message_id: int | None = None
    if answer.strip():
        saved = await add_message(
            HrMessage(thread_id=thread.id, kind="llm_assistant", body=answer.strip()),
            account_id=account_id,
            db=db,
        )
        answer_message_id = saved.id
    return LlmExchangeResult(
        thread=thread,
        question_message_id=question_message_id,
        answer_message_id=answer_message_id,
    )


__all__ = [
    "HrThread",
    "HrMessage",
    "LlmExchangeResult",
    "UnansweredThread",
    "HR_KINDS",
    "save_thread",
    "list_threads_by_vacancy",
    "list_recent_threads",
    "list_archived_vacancy_ids",
    "list_recent_hr_contacts",
    "count_active_threads",
    "archive_threads_for_vacancy",
    "unarchive_threads_for_vacancy",
    "list_unanswered_threads",
    "chat_velocity_signals",
    "get_thread",
    "get_primary_thread",
    "get_or_create_thread",
    "update_thread",
    "set_funnel_suggestion",
    "clear_funnel_suggestion",
    "delete_thread",
    "add_message",
    "add_messages",
    "append_llm_exchange",
    "list_messages",
    "get_message",
    "delete_message",
    "format_hr_feed",
    "RecentHrContact",
]
