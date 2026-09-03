-- 0026_mock_sessions — тренажёр: мок-собес в чате (JS-12). Одна строка = одна законченная сессия
-- (вопросы + полный транскрипт по-вопросно + финальная сводка). Живой диалог по ходу сессии
-- держит фронт (история хода по текущему вопросу шлётся в каждом /api/mock/turn, как у Q&A с
-- AskMessage) — в БД пишем только по завершении, поэтому таблица без промежуточных апдейтов.
-- По образцу interview_debriefs (0016)/stage_outcomes (0020): vacancy_id = HH id, БЕЗ FK на jobs;
-- здесь vacancy_id ещё и nullable — сессия может быть без привязки к вакансии (общая тренировка).
create table mock_sessions (
    id               bigint      generated always as identity primary key,
    vacancy_id       text,
    stage            text        not null default 'tech',
    questions        jsonb       not null default '[]'::jsonb,
    transcript       jsonb       not null default '[]'::jsonb,
    strengths        jsonb       not null default '[]'::jsonb,
    weak_areas       jsonb       not null default '[]'::jsonb,
    competency_map   jsonb       not null default '[]'::jsonb,
    summary          text        not null default '',
    skipped_count    integer     not null default 0,
    answered_count   integer     not null default 0,
    created_at       timestamptz not null default now()
);
-- vacancy_id + свежесть — история сессий по вакансии (свежие первыми, как load_debrief_history).
-- vacancy_id может быть NULL (сессии без вакансии в эту выборку не попадают — им нужна отдельная
-- лента «последние сессии», не реализуем в JS-12.1, UI полностью в JS-12.2).
create index mock_sessions_vacancy_idx on mock_sessions (vacancy_id, created_at desc);
