-- 0034_data_to_pg — перенос содержимого data/ в Postgres: manifest ингеста Drive, журнал
-- guard-скана HR-пересылок, пресеты discovery. Заменяет JSON/JSONL-файлы (антипаттерн: данные
-- в файлах вместо БД). Cost-учёт LLM уже в llm_usage (0004); JSONL-фоллбэк убран.

-- Манифест ингеста Drive: file_id → подпись/кол-во эпизодов. Повторный запуск пропускает
-- файлы с неизменившейся подписью. upsert по file_id (одна запись на файл, перезапись).
create table if not exists drive_ingest_manifest (
    file_id     text        not null primary key,
    name        text        not null default '',
    path        text        not null default '',
    signature   text        not null default '',
    episodes    int         not null default 0,
    ingested_at timestamptz not null default now()
);

-- Журнал guard-скана HR-пересылок (пилот guardrails): сырой вход + результат скана.
-- Append-only, как inbox.jsonl; jsonb для scan-результата (модель guard_scan).
create table if not exists hr_forward_journal (
    id          bigint      generated always as identity primary key,
    ts          timestamptz not null default now(),
    chat_id     bigint,
    text        text        not null default '',
    scan        jsonb       not null default '{}'::jsonb
);
create index if not exists hr_forward_journal_ts_idx on hr_forward_journal (ts desc);

-- Пресеты discovery (имя → search-URL hh.ru). upsert по name (одна запись на пресет).
create table if not exists discovery_presets (
    name        text        not null primary key,
    url         text        not null,
    updated_at  timestamptz not null default now()
);
