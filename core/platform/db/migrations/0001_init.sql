-- 0001_init — реляционная модель Career & Relocation Copilot (задача 1.1, В2.1/В2.2).
-- Postgres — операционка (jobs/funnel/tasks/usage/...); знания и plan-граф живут в Neo4j.
-- Конвенции: все метки времени timestamptz; enum'ы = text + CHECK; jsonb для гибких payload.
-- gen_random_uuid() встроен в PG13+, pgcrypto на всякий случай (старые сборки).

create extension if not exists pgcrypto;

-- Профиль владельца — синглтон (single-user система).
create table profile (
    id          integer primary key default 1 check (id = 1),
    data        jsonb       not null default '{}'::jsonb,
    updated_at  timestamptz not null default now()
);

-- Вакансии: основа из VacancyRecord/ScoreResult. score — полный ScoreResult (jsonb),
-- salary — выжимка SalaryInfo для быстрых выборок, overall_score/recommendation/work_city
-- денормализованы (порог графа в 1.5, сортировка kanban). vacancy_id (HH id) — ключ upsert.
create table jobs (
    id                bigint generated always as identity primary key,
    vacancy_id        text unique,
    url               text,
    title             text,
    company           text,
    vacancy_text      text        not null,
    salary_text       text,
    area              text,
    work_schedule     text,
    total_responses   integer,
    letter_required   boolean,
    published_at      text,
    cover_letter_text text,
    employer_id       text,
    source            text,
    is_archived       boolean     not null default false,
    status            text,
    overall_score     integer,
    recommendation    text,
    work_city         text,
    score             jsonb       not null default '{}'::jsonb,
    salary            jsonb,
    scored_at         timestamptz not null default now(),
    created_at        timestamptz not null default now(),
    updated_at        timestamptz not null default now()
);
create index jobs_overall_score_idx on jobs (overall_score desc);
create index jobs_status_idx on jobs (status);

-- Стадии воронки: история переходов (источник hh/hr/bot/manual → событие replanning в 2.2).
create table application_stages (
    id          bigint generated always as identity primary key,
    job_id      bigint      not null references jobs (id) on delete cascade,
    stage       text        not null,
    source      text        not null default 'manual',
    changed_at  timestamptz not null default now()
);
create index application_stages_job_id_idx on application_stages (job_id);

-- Задачи оркестратора (LangGraph thread_id = id, Фаза 2). payload/result — jsonb-конверты.
create table agent_tasks (
    id          uuid        primary key default gen_random_uuid(),
    type        text        not null,
    status      text        not null default 'pending'
        check (status in ('pending', 'running', 'waiting_hitl', 'done', 'error', 'cancelled')),
    payload     jsonb       not null default '{}'::jsonb,
    result      jsonb,
    thread_id   text,
    error       text,
    created_at  timestamptz not null default now(),
    finished_at timestamptz
);
create index agent_tasks_status_idx on agent_tasks (status);

-- Уведомления (Telegram/UI): завершение задач, cost-алёрт, дедлайны, HITL.
create table notifications (
    id          bigint generated always as identity primary key,
    kind        text        not null,
    channel     text        not null default 'telegram',
    payload     jsonb       not null default '{}'::jsonb,
    sent_at     timestamptz,
    created_at  timestamptz not null default now()
);

-- Логи интервью (prep/debrief/offer; debrief даёт Lesson-узлы в граф, 4.2).
create table interview_logs (
    id          bigint generated always as identity primary key,
    job_id      bigint      references jobs (id) on delete set null,
    company     text,
    kind        text        not null,
    payload     jsonb       not null default '{}'::jsonb,
    created_at  timestamptz not null default now()
);

-- Документы (источник из Drive-папки, 3.2). content_hash — манифест инкрементального ингеста.
-- id используется как общий ключ зеркала в Neo4j (1.2).
create table documents (
    id           bigint generated always as identity primary key,
    path         text        not null,
    title        text,
    kind         text,
    content_hash text,
    meta         jsonb       not null default '{}'::jsonb,
    created_at   timestamptz not null default now(),
    updated_at   timestamptz not null default now()
);
create index documents_content_hash_idx on documents (content_hash);

-- Визовые задачи. depends_on — id других visa_items (граф зависимостей). Зеркало в Neo4j (1.2).
create table visa_items (
    id           bigint generated always as identity primary key,
    jurisdiction text        not null,
    title        text        not null,
    status       text        not null default 'todo'
        check (status in ('todo', 'in_progress', 'done', 'blocked', 'obsolete')),
    deadline     timestamptz,
    depends_on   bigint[]    not null default '{}',
    meta         jsonb       not null default '{}'::jsonb,
    created_at   timestamptz not null default now(),
    updated_at   timestamptz not null default now()
);

-- Портфолио под визовые критерии (O-1/EB-1 и т.п.). Зеркало в Neo4j (1.2).
create table portfolio_items (
    id             bigint generated always as identity primary key,
    title          text        not null,
    visa_criterion text,
    status         text        not null default 'todo',
    meta           jsonb       not null default '{}'::jsonb,
    created_at     timestamptz not null default now(),
    updated_at     timestamptz not null default now()
);

-- Финансовые снимки (остатки/доход/расход — материал finance-агента из бэклога).
create table finance_snapshots (
    id          bigint generated always as identity primary key,
    snapshot_at timestamptz not null default now(),
    currency    text        not null default 'USD',
    data        jsonb       not null default '{}'::jsonb
);

-- Журнал присутствия по юрисдикциям (счётчик 183 дней). Один день на юрисдикцию.
create table residency_day_log (
    id           bigint generated always as identity primary key,
    jurisdiction text    not null,
    day          date    not null,
    present      boolean not null default true,
    note         text,
    unique (jurisdiction, day)
);

-- Прогресс по английскому (IELTS/словарь/...).
create table english_progress (
    id          bigint generated always as identity primary key,
    measured_at timestamptz not null default now(),
    metric      text        not null,
    value       text        not null,
    note        text
);

-- Контакты HR (вход для калибровки и будущего hr_outreach).
create table hr_contacts (
    id          bigint generated always as identity primary key,
    name        text,
    company     text,
    tg_user_id  text,
    tg_username text,
    job_id      bigint      references jobs (id) on delete set null,
    meta        jsonb       not null default '{}'::jsonb,
    created_at  timestamptz not null default now(),
    updated_at  timestamptz not null default now()
);

-- Cost-учёт LLM (Критерий 3). Заменяет JSONL из 0.2; day денормализован под дневные агрегаты.
create table llm_usage (
    id          bigint generated always as identity primary key,
    ts          timestamptz   not null default now(),
    day         date          not null default current_date,
    agent       text          not null,
    model       text          not null,
    tokens_in   integer       not null default 0,
    tokens_out  integer       not null default 0,
    cost_usd    numeric(12, 6) not null default 0
);
create index llm_usage_day_idx on llm_usage (day);
create index llm_usage_agent_idx on llm_usage (agent);

-- Вердикты judge (1.4) + ground truth от человека (agreement-петля, Критерий 3).
create table judge_feedback (
    id            bigint generated always as identity primary key,
    artifact_ref  text,
    rubric        text,
    judge_verdict jsonb       not null default '{}'::jsonb,
    human_verdict jsonb,
    created_at    timestamptz not null default now()
);

-- Сессии фронта (логин/пароль → cookie, В13.3). Расширение ходит по X-API-Key, тут не пишется.
create table auth_sessions (
    token      text        primary key,
    created_at timestamptz not null default now(),
    expires_at timestamptz,
    meta       jsonb       not null default '{}'::jsonb
);
