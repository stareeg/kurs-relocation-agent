"""Guard: account-скоуп таблицы объявлены с account_id + RLS + grant (plan §1, по духу
test_migration_numbers.py — текстовый sync-тест, без живой БД, ловит дрейф для любого
контрибьютора без Postgres под рукой).

`test_every_live_table_is_classified` — denylist, инверсия исходной версии этого файла (M0,
plans/multitenancy_gaps_2026_08_06.md §1, §6): раньше тест перечислял только таблицы, которые
*обязаны* быть account-скоуп, и новая таблица без account_id его не роняла. Теперь классификации
подлежит КАЖДАЯ живая таблица (см. `_live_tables`) — попадание ровно в один из трёх списков
(ACCOUNT_SCOPED / GLOBAL_REFERENCE / SYSTEM) обязательно; таблица без классификации роняет
тест с текстом «реши, чья это строка». Список тянется из миграций динамически, а не хардкодится
числом — 0110 появится и тоже потребует решения.

`test_account_scoped_tables_have_account_id_and_rls` — как раньше: для таблиц, ретрофит которых
уже сделан (подмножество ACCOUNT_SCOPED), account_id/RLS/policy/grant обязаны реально быть в
миграциях. Для остального ACCOUNT_SCOPED (ещё не ретрофичено — см. комментарии по M-этапам)
эта проверка не требуется: они попадают в план поэтапно (M1..M9), а не все сразу.

Поведенческая проверка, что RLS реально режет чужие строки — tests/test_rls_accounts.py и
соседние test_rls_*.py (маркер `db`, требуют живой Postgres).
"""

from __future__ import annotations

import re
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
MIGRATIONS_DIR = ROOT / "core" / "platform" / "db" / "migrations"

# ---------------------------------------------------------------------------------------------
# Классификация: КАЖДАЯ живая таблица — ровно в одном из трёх множеств (план §2). Комментарии —
# обоснование, не декорация: следующий контрибьютор должен по ним понять, куда положить 0110.
# ---------------------------------------------------------------------------------------------

# Личные данные аккаунта — обязаны в итоге получить account_id + RLS. Часть уже ретрофичена
# (см. REQUIRED_ACCOUNT_SCOPED_TABLES/REQUIRED_RLS_ONLY_TABLES ниже, строгая проверка); для
# остальных account_id ещё предстоит добавить — конкретный M-этап указан в комментарии
# (plans/multitenancy_gaps_2026_08_06.md §6).
ACCOUNT_SCOPED = {
    # identity сама по себе — account_id не колонка, а сама строка (RLS без колонки).
    "accounts",
    # --- ретрофичено (Этапы 1-5 vm_multitenant_hosting_2026_08_03.md, инвентарь) ---
    "account_settings",
    # 0107_account_telegram_links.sql: доп. Telegram-identity аккаунта («Добавить аккаунт»,
    # TG-bot запрос 2026-08-06) — account_id/RLS/policy/grant заведены с нуля, не ретрофит.
    "account_telegram_links",
    # 0108_account_sessions.sql: многоустройственные сессии входа (замена одной колонки
    # web_auth_token_sha256 на accounts) — тоже с нуля, не ретрофит.
    "account_sessions",
    "jobs",
    "application_stages",
    "score_revisions",
    "skipped_vacancies",
    "vacancy_enrichment",
    "hr_threads",
    "hr_messages",
    "hr_vacancy_links",
    # 0123_job_links.sql: площадочные ссылки одной логической вакансии (дедупликация S12).
    # account_id с нуля в CREATE TABLE — аккаунт-связанные данные.
    "job_links",
    "stage_outcomes",
    "tg_hr_pending",
    "interview_stages",
    "resumes",
    "openrouter_key_requests",
    # 0141_openrouter_account_keys.sql: происхождение действующего ключа OpenRouter (маска,
    # метка, кто выдал) — account_id тут PK, новая таблица с нуля, как resumes.
    "openrouter_account_keys",
    # --- M1: резюме-скор и производные ---
    "resume_score_history",
    "resume_stats",
    "resume_views",
    "resume_skill_snapshots",
    "resume_skill_suggestions",
    # --- 0125_gm_profile_snapshots.sql: снимки getmatch-профиля (GM-13) ---
    # Личные данные аккаунта (профиль кандидата getmatch), account_id/RLS/policy/grant с нуля.
    "gm_profile_snapshots",
    # --- 0126_gm_trust_snapshots.sql: снимки чеклиста доверия getmatch (GM-12) ---
    # Личные данные аккаунта (заполненность профиля кандидата getmatch), account_id/RLS/policy/grant
    # с нуля (как gm_profile_snapshots/0125).
    "gm_trust_snapshots",
    # --- 0131_auto_apply_queue_override.sql: редизайн «Расширения» (Фаза E) ---
    # Ручной оверрайд бакета auto/manual_review — личное решение владельца, account_id/RLS/
    # policy/grant с нуля в CREATE TABLE (как gm_trust_snapshots/0126).
    "auto_apply_queue_overrides",
    # --- M2: офферы ---
    "offers",
    "offer_comparisons_cache",
    # --- M3: подготовка — технички/скрининги/дебрифы/чат по вакансии ---
    "prep_sessions",
    "prep_packs",
    "prep_topics",
    "prep_reminders",
    "interview_debriefs",
    "debrief_attachments",
    "vacancy_screening_questions",
    "prep_chat_messages",
    "prep_chat_message_attachments",
    "competency_ledger",
    # --- M4: заметки, вложения, HR-пересылки ---
    "notes",
    "note_messages",
    "attachments",
    "hr_message_attachments",
    "hr_forward_journal",
    # --- M5: рынок / режим поиска / career / калибровка ---
    "search_state_log",
    "situation_narratives",
    "market_analytics_snapshot",
    "market_snapshots",
    "discovery_presets",
    "tg_ui_messages",  # де-факто изолирована по chat_id; account_id — для FK/единообразия
    "salary_calibration_queue",  # де-факто изолирована по chat_id
    "salary_calibration_sessions",  # де-факто изолирована по chat_id
    "salary_calibration_samples",  # личные наблюдения (решение владельца 2026-08-06, план §9 п.1)
    "salary_calibration_meta",  # то же — составной PK (account_id, key)
    "career_timeline",
    "career_portfolio_items",
    "career_facts",
    # --- M6: платформа — usage / очередь ---
    "llm_usage",
    "background_tasks",  # там, где задача аккаунтная — системные kind перечисляются явно
    # --- 0110_resume_chat_messages.sql: чат по резюме (вкладка «Резюме») ---
    # Лента реплик user/assistant на аккаунт — личные данные владельца, account_id/RLS с нуля
    # (как resume_skill_snapshots/prep_chat_messages, не ретрофит).
    "resume_chat_messages",
    # --- 0111_market_chat_messages.sql: чат по ситуации на рынке (вкладка «Рынок») ---
    # Заменил блок «Что сделать» (next-steps) на свободный диалог с карьерным стратегом.
    # account_id/RLS/policy/grant с нуля в CREATE TABLE (как resume_chat_messages).
    "market_chat_messages",
    # --- 0112_job_skip_reasons.sql: LLM-сгенерированные чипы причин пропуска ---
    # 6 конкретных причин под вакансию (после скоринга). Личные данные аккаунта:
    # причины генерируются под резюме/скор аккаунта, account_id/RLS с нуля в CREATE TABLE.
    "job_skip_reasons",
    # --- 0115_market_chat_replies_attachments.sql: вложения чата «Рынка» ---
    # Денормализует account_id от market_chat_messages — своя пара link_*/load_* функций
    # (не общий реестр _SURFACE_TABLES), как prep_chat_message_attachments/0104.
    # account_id/RLS/policy/grant с нуля в CREATE TABLE (не ретрофит).
    "market_chat_message_attachments",
    # --- 0120_resume_chat_replies_attachments.sql: ответ на сообщение + вложения чата по резюме ---
    # Зеркало 0115 (market_chat): reply_to_message_id на resume_chat_messages + отдельная
    # таблица связок resume_chat_message_attachments с account_id/RLS с нуля в CREATE TABLE.
    "resume_chat_message_attachments",
    # --- 0135_offers_chat_messages.sql: чат вкладки «Офферы» ---
    # Лента реплик user/assistant на аккаунт + связки вложений. account_id/RLS/policy/grant
    # с нуля в CREATE TABLE (зеркало 0111+0115 market / 0110+0120 resume).
    "offers_chat_messages",
    "offers_chat_message_attachments",
    # --- 0121_friendships.sql: коды дружбы + связи ---
    # Личные данные аккаунта: код для шаринга и список друзей. account_id в CREATE TABLE,
    # но RLS/policy/grant ещё не добавлены (будет следующим M-этапом).
    "account_friendship_codes",
    "friendships",
    # --- 0132/0133: трек поиска и снимок международного опыта (Э1 dual employment) ---
    "search_track_log",
    "international_profile_snapshots",
    # --- 0148_employer_descriptors.sql: дескрипторы работодателей для деперсонализации (Э4.1) ---
    # Личные данные аккаунта (обобщение своего работодателя). account_id/RLS/policy/grant
    # с нуля в CREATE TABLE.
    "employer_descriptors",
}

# Один и тот же контент для всех аккаунтов по построению — объективные данные/кэш из
# публичного источника (JD-текст, страницы hh), не персональные. Не трогать при ретрофите.
GLOBAL_REFERENCE = {
    "vacancy_skill_requirements",  # кэш требований, разобранных из текста JD — объективен
    "vacancy_work_terms",  # кэш условий работы из текста JD — объективен (Э2.1)
    "market_demand_readings",  # съёмы с публичных страниц hh
    "market_index_readings",  # то же
}

# Инфраструктурные — не принадлежат ни одному аккаунту по смыслу (кэш по хэшу промпта,
# системный лог, синглтон-настройки, манифесты синхронизации). copilot_logs получит account_id
# как поле для фильтра бандла, но это не делает её account-скоуп по PK/FK.
SYSTEM = {
    "llm_result_cache",  # ключ = хэш полного промпта — контент не течёт даже без account_id
    "copilot_logs",  # account_id — поле для фильтра выдачи, не PK; бандл — только по своим
    "admin_audit",  # реестр действий оператора установки (Этап 5.4) — не данные аккаунта
    "admin_support_messages",  # лента поддержки в карточке человека: агент скрыт от человека
    "app_settings",  # 2 системных ключа (см. core/platform/repo/settings.py), не аккаунтные
    "getmatch_sync_freshness",  # синглтон sync-состояния
    # 0139: CSS-селекторы парсера hh — одни на установку, SQL-оверрайд без деплоя.
    "parser_selector_configs",
    # 0151: лобби столов мультиплеера — общие комнаты (SI-style), изоляция в service, не RLS.
    "mp_rooms",
    "mp_seats",
}

CLASSIFIED_TABLES = ACCOUNT_SCOPED | GLOBAL_REFERENCE | SYSTEM

# Таблицы, обязанные быть account-скоуп УЖЕ СЕЙЧАС (ретрофит завершён — строгая проверка ниже).
# Растёт по мере ретрофита доменов (план §6); остальное в ACCOUNT_SCOPED пока только
# классифицировано, но не проверяется на факт наличия account_id/RLS.
# vacancy_skill_requirements НЕ входит — кэш навыков из текста JD объективен (см. GLOBAL_REFERENCE).
REQUIRED_ACCOUNT_SCOPED_TABLES = [
    "account_settings",
    # 0107_account_telegram_links.sql — новая таблица с нуля (как resumes/openrouter_key_requests
    # ниже), не ретрофит: account_id/RLS/policy/grant заведены сразу в CREATE TABLE.
    "account_telegram_links",
    # 0108_account_sessions.sql — то же самое: account_id/RLS/policy/grant с нуля.
    "account_sessions",
    # Домен 1 (0097_pipeline_account_id.sql, plans/vm_multitenant_hosting_2026_08_03.md §9):
    # jobs/hr_threads изначально заведены без account_id (0001/0019/…) — колонка и NOT NULL
    # пришли позже отдельным ALTER, поэтому _has_account_id_column ищет не только исходный
    # CREATE TABLE, но и такой retrofit-паттерн.
    "jobs",
    "application_stages",
    "score_revisions",
    "skipped_vacancies",
    "vacancy_enrichment",
    "hr_threads",
    "hr_messages",
    "hr_vacancy_links",
    # 0123: создана с нуля с account_id, как hr_vacancy_links.
    "job_links",
    "stage_outcomes",
    "tg_hr_pending",
    # Этап 4 (0098_resumes.sql, план §6): резюме переехало с файла в БД — account_id тут PK,
    # не отдельная колонка-ALTER (не ретрофит существующей таблицы, а новая с нуля).
    "resumes",
    # Этап 5 (0099_openrouter_key_requests.sql, план §4): заявки на ключ OpenRouter —
    # account_id заявителя, новая таблица с нуля (как resumes).
    "openrouter_key_requests",
    # 0141_openrouter_account_keys.sql: происхождение выданного ключа — account_id/RLS/policy/
    # grant заведены сразу в CREATE TABLE.
    "openrouter_account_keys",
    # Этап 3, домен 2 (0100_interview_stages_account_id.sql) — ретрофит существующей таблицы
    # (0006), не новая с нуля; найдено при попытке открыть HR-пайплайн/дайджест для member'ов.
    "interview_stages",
    # M1 (0101_resume_account_id.sql, plans/multitenancy_gaps_2026_08_06.md §3.1/§6): резюме-скор
    # и его производные — ретрофит существующих таблиц (0017/0027/0082), тот самый S1-баг
    # «резюме друга стало резюме для всех».
    "resume_score_history",
    "resume_stats",
    "resume_views",
    "resume_skill_snapshots",
    # resume_skill_suggestions денормализует account_id от resume_skill_snapshots (снимка) —
    # тот же приём, что hr_messages от hr_threads в 0097 (RLS-политике нужна колонка на строке).
    "resume_skill_suggestions",
    # 0125_gm_profile_snapshots.sql — снимки getmatch-профиля (GM-13): account_id/RLS/policy/grant
    # с нуля в CREATE TABLE, не ретрофит (как resume_chat_messages/0110).
    "gm_profile_snapshots",
    # 0126_gm_trust_snapshots.sql — снимки чеклиста доверия getmatch (GM-12): account_id/RLS/policy/grant
    # с нуля в CREATE TABLE (как gm_profile_snapshots/0125).
    "gm_trust_snapshots",
    # 0131_auto_apply_queue_override.sql — ручной оверрайд бакета очереди автооткликов (Фаза E
    # редизайна «Расширения»): account_id/RLS/policy/grant с нуля в CREATE TABLE (как
    # gm_trust_snapshots/0126).
    "auto_apply_queue_overrides",
    # 0132_search_track_log.sql / 0133_international_profile_snapshots.sql — Э1 dual employment:
    # журнал треков и кэш международного снимка. account_id/RLS/policy/grant с нуля.
    "search_track_log",
    "international_profile_snapshots",
    # M2 (0102_offers_account_id.sql, plans/multitenancy_gaps_2026_08_06.md §3.2/§6): офферы —
    # было PK(vacancy_id) → PK(account_id, vacancy_id) (тот же приём, что vacancy_enrichment
    # в 0097), тот самый S1-баг «два аккаунта с оффером по одной вакансии пишут в одну строку».
    "offers",
    # offer_comparisons_cache — было unique(vacancy_ids_hash) → unique(account_id, vacancy_ids_hash).
    "offer_comparisons_cache",
    # M3 (0104_prep_account_id.sql, plans/multitenancy_gaps_2026_08_06.md §3.3/§6): подготовка —
    # технички/скрининги/дебрифы/чат по вакансии/карта компетенций.
    "prep_sessions",
    "prep_reminders",
    # prep_packs — было PK(vacancy_id, stage) → PK(account_id, vacancy_id, stage) (тот же приём,
    # что offers/prep_packs в 0102).
    "prep_packs",
    # prep_topics — было unique(vacancy_id, stage, topic) → unique(account_id, vacancy_id, stage, topic).
    "prep_topics",
    "interview_debriefs",
    # debrief_attachments денормализует account_id от interview_debriefs (тот же приём, что
    # resume_skill_suggestions/hr_messages выше).
    "debrief_attachments",
    # vacancy_screening_questions — было PK(vacancy_id) → PK(account_id, vacancy_id).
    "vacancy_screening_questions",
    "prep_chat_messages",
    # prep_chat_message_attachments денормализует account_id от prep_chat_messages — своя пара
    # repo-функций (link_prep_chat_attachments/load_prep_chat_attachments), не общий реестр
    # _SURFACE_TABLES (hr_message_attachments там же, но без account_id до M4).
    "prep_chat_message_attachments",
    "competency_ledger",
    # M4 (0105_notes_attachments_account_id.sql, plans/multitenancy_gaps_2026_08_06.md §3.4/§3.5/§6):
    # заметки, вложения-картинки, HR-guard-журнал.
    "notes",
    # note_messages денормализует account_id от notes (note_id) — тот же приём, что
    # debrief_attachments/hr_message_attachments выше.
    "note_messages",
    # attachments — было unique(sha256), одна таблица-хранилище на всю систему; стало
    # unique(account_id, sha256) (§3.5: IDOR через глобальный id/sha256 — «перебор id выдаёт
    # чужие скриншоты переписок и офферов»).
    "attachments",
    # hr_message_attachments денормализует account_id от hr_messages (message_id) — своя пара
    # repo-функций (link_hr_message_attachments/load_hr_message_attachments), тот же приём, что
    # debrief_attachments/prep_chat_message_attachments в M3.
    "hr_message_attachments",
    "hr_forward_journal",
    # M5 (0106_market_career_account_id.sql, plans/multitenancy_gaps_2026_08_06.md §3.6/§3.7/§6):
    # рынок, режим поиска, career, калибровка.
    "search_state_log",
    "situation_narratives",
    # market_analytics_snapshot — было PK(kind) → PK(account_id, kind) (§3.6: один кэш на всю
    # систему, аккаунты перезатирали друг другу снимок).
    "market_analytics_snapshot",
    # market_snapshots — было unique(day) → unique(account_id, day).
    "market_snapshots",
    # discovery_presets — было PK(name) → PK(account_id, name).
    "discovery_presets",
    # tg_ui_messages — де-факто изолирована по chat_id; account_id для FK/единообразия
    # (низкий приоритет, план §2).
    "tg_ui_messages",
    # salary_calibration_queue/sessions — де-факто изолированы по chat_id, account_id добавлен
    # для FK/единообразия и будущего RLS.
    "salary_calibration_queue",
    "salary_calibration_sessions",
    # salary_calibration_samples/_meta — решение владельца 2026-08-06 (план §9 п.1): личные
    # наблюдения аккаунта, не общий корпус. meta — было PK(key) → PK(account_id, key).
    "salary_calibration_samples",
    "salary_calibration_meta",
    # career_* (0070/0074, чистка 0150) — timeline/portfolio/facts.
    "career_timeline",
    "career_portfolio_items",
    "career_facts",
    # 0110_resume_chat_messages.sql — чат по резюме аккаунта (вкладка «Резюме»): account_id/RLS/
    # policy/grant заведены с нуля в CREATE TABLE (как resume_skill_snapshots/prep_chat_messages).
    "resume_chat_messages",
    # 0111_market_chat_messages.sql — чат по ситуации на рынке (вкладка «Рынок»): то же —
    # account_id/RLS/policy/grant с нуля в CREATE TABLE, не ретрофит.
    "market_chat_messages",
    # 0120_resume_chat_replies_attachments.sql — таблица связок вложений чата по резюме:
    # account_id/RLS/policy/grant с нуля в CREATE TABLE (зеркало 0115/market_chat_message_attachments).
    "resume_chat_message_attachments",
    # 0135_offers_chat_messages.sql — чат вкладки «Офферы»: account_id/RLS/policy/grant
    # с нуля в CREATE TABLE (зеркало 0111+0115 market / 0110+0120 resume).
    "offers_chat_messages",
    "offers_chat_message_attachments",
]

# Таблицы без колонки account_id, у которых тем не менее обязана быть включена RLS с самого
# начала (идентичность == сама строка, не отдельная колонка). Сегодня — только accounts.
REQUIRED_RLS_ONLY_TABLES = ["accounts"]

assert set(REQUIRED_ACCOUNT_SCOPED_TABLES) <= ACCOUNT_SCOPED, (
    "REQUIRED_ACCOUNT_SCOPED_TABLES должен быть подмножеством ACCOUNT_SCOPED — если таблица "
    "уже ретрофичена, она обязана быть и классифицирована"
)
assert set(REQUIRED_RLS_ONLY_TABLES) <= ACCOUNT_SCOPED


def _all_migrations_sql() -> str:
    return "\n".join(p.read_text(encoding="utf-8") for p in sorted(MIGRATIONS_DIR.glob("*.sql")))


_CREATE_TABLE_RE = re.compile(
    r"create table\s+(?:if not exists\s+)?([a-z_][a-z0-9_]*)", re.IGNORECASE
)
_DROP_TABLE_RE = re.compile(r"drop table\s+(?:if exists\s+)?([a-z_][a-z0-9_]*)", re.IGNORECASE)


def _live_tables(sql: str) -> set[str]:
    """CREATE TABLE, минус те, что позже DROP TABLE в этой же истории миграций.

    Множества, не «последняя инструкция побеждает» — в этой кодовой базе ни одна таблица не
    пересоздавалась после дропа, а множество проще и достаточно для guard-теста.
    """
    created = {m.group(1).lower() for m in _CREATE_TABLE_RE.finditer(sql)}
    dropped = {m.group(1).lower() for m in _DROP_TABLE_RE.finditer(sql)}
    return created - dropped


def _extract_table_block(sql: str, table: str) -> str | None:
    """Текст между `create table ... {table} (` и его закрывающей `)` (учёт вложенных скобок)."""
    pattern = re.compile(
        rf"create table\s+(?:if not exists\s+)?{re.escape(table)}\s*\(", re.IGNORECASE
    )
    match = pattern.search(sql)
    if match is None:
        return None
    depth = 1
    i = match.end()
    start = i
    while i < len(sql) and depth > 0:
        if sql[i] == "(":
            depth += 1
        elif sql[i] == ")":
            depth -= 1
        i += 1
    return sql[start : i - 1]


def _has_account_id_column(sql: str, table: str) -> bool:
    """account_id NOT NULL — либо в исходном CREATE TABLE, либо задним числом через ALTER
    (retrofit существующей таблицы: `add column account_id bigint` + отдельный `alter column
    ... set not null` после backfill, см. 0097_pipeline_account_id.sql)."""
    block = _extract_table_block(sql, table)
    if block and re.search(r"account_id\s+bigint\s+not null", block, re.IGNORECASE):
        return True
    add_column = re.search(
        rf"alter table\s+{re.escape(table)}\s+add column account_id\s+bigint\b", sql, re.IGNORECASE
    )
    set_not_null = re.search(
        rf"alter table\s+{re.escape(table)}\s+alter column account_id set not null",
        sql,
        re.IGNORECASE,
    )
    return bool(add_column and set_not_null)


def _has_rls_enabled(sql: str, table: str) -> bool:
    return (
        re.search(rf"alter table\s+{re.escape(table)}\s+enable row level security", sql, re.IGNORECASE)
        is not None
    )


def _has_policy(sql: str, table: str) -> bool:
    return re.search(rf"create policy\s+\S+\s+on\s+{re.escape(table)}\b", sql, re.IGNORECASE) is not None


_GRANT_STATEMENT_RE = re.compile(r"grant\s+.*?\bto\b[^;]*;", re.IGNORECASE | re.DOTALL)


def _has_rls_grant(sql: str, table: str) -> bool:
    """`grant ... on <table[, ...]> to app_rls[, app_admin];` — без него `app_rls` не видит
    таблицу вообще («не существует» для всего продукта), даже если RLS-политика написана
    правильно (план §1, «Заодно» — тот же класс ошибки, что забытая колонка)."""
    for stmt in _GRANT_STATEMENT_RE.finditer(sql):
        text = stmt.group(0)
        if "app_rls" not in text.lower():
            continue
        tables_part = re.search(r"\bon\b(.*?)\bto\b", text, re.IGNORECASE | re.DOTALL)
        if not tables_part:
            continue
        tables = {t.strip().lower() for t in tables_part.group(1).split(",")}
        if table in tables:
            return True
    return False


def test_every_live_table_is_classified() -> None:
    """Denylist: таблица без комментария-обоснования в одном из трёх списков выше
    роняет тест — не даёт добавить таблицу 0110 и забыть решить, чья это строка."""
    sql = _all_migrations_sql()
    live = _live_tables(sql)

    unclassified = sorted(live - CLASSIFIED_TABLES)
    assert not unclassified, (
        "Таблицы без классификации ACCOUNT_SCOPED/GLOBAL_REFERENCE/SYSTEM — реши, чья это "
        "строка (plan §1), и добавь в tests/test_tenant_columns_present.py:\n  - "
        + "\n  - ".join(unclassified)
    )

    # Обратная сторона: список не должен зачахнуть и указывать на дропнутые/переименованные
    # таблицы — иначе он молча перестаёт что-либо гарантировать (мёртвая запись хуже
    # отсутствующей).
    stale = sorted(CLASSIFIED_TABLES - live)
    assert not stale, (
        "Таблицы в классификации, которых больше нет среди живых миграций (дропнуты/"
        "переименованы) — убери из списков в tests/test_tenant_columns_present.py:\n  - "
        + "\n  - ".join(stale)
    )


def test_account_scoped_tables_have_account_id_and_rls() -> None:
    sql = _all_migrations_sql()
    problems: list[str] = []

    for table in REQUIRED_ACCOUNT_SCOPED_TABLES:
        if _extract_table_block(sql, table) is None:
            problems.append(f"{table}: CREATE TABLE не найден в миграциях")
            continue
        if not _has_account_id_column(sql, table):
            problems.append(f"{table}: нет колонки account_id bigint not null")
        if not _has_rls_enabled(sql, table):
            problems.append(f"{table}: нет ENABLE ROW LEVEL SECURITY")
        if not _has_policy(sql, table):
            problems.append(f"{table}: нет CREATE POLICY")
        if not _has_rls_grant(sql, table):
            problems.append(f"{table}: нет GRANT ... TO app_rls")

    assert not problems, (
        "Account-скоуп таблицы без RLS-фундамента (плана):\n  - " + "\n  - ".join(problems)
    )


def test_accounts_table_has_rls() -> None:
    sql = _all_migrations_sql()
    problems: list[str] = []

    for table in REQUIRED_RLS_ONLY_TABLES:
        if _extract_table_block(sql, table) is None:
            problems.append(f"{table}: CREATE TABLE не найден в миграциях")
            continue
        if not _has_rls_enabled(sql, table):
            problems.append(f"{table}: нет ENABLE ROW LEVEL SECURITY")
        if not _has_policy(sql, table):
            problems.append(f"{table}: нет CREATE POLICY")
        if not _has_rls_grant(sql, table):
            problems.append(f"{table}: нет GRANT ... TO app_rls")

    assert not problems, "Таблицы без RLS (плана):\n  - " + "\n  - ".join(problems)
