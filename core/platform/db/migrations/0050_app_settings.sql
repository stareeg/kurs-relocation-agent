-- 0050_app_settings — FR-11: «Параметры» — простой key/value для one-user системы, без
-- over-engineering (одна таблица вместо нескольких строго типизированных). Значения читаются
-- через core.repo.settings (FR-12), которая не существует ещё в этом шаге — сама миграция только
-- заводит таблицу и сидирует текущие хардкод-значения владельца, чтобы после переноса констант в
-- Python (Блок II-III) поведение для владельца не изменилось молча.
--
-- Ключи:
--   scoring_weights        — 5 чисел, сумма = 100 (core.scoring.score_breakdown, EXT-S1).
--   company_adjustments    — список {match, delta, reason, cap} (FR-10, CompanyAdjustmentRule).
--   salary_min_override    — nullable int; если задан, перебивает resume.position.salary_min.
--   daily_cost_limit_usd / daily_cost_hard_limit_usd — дублируют .env-дефолты (core/config.py),
--                             переопределяемы без рестарта.
--   openrouter_api_key     — nullable string, секрет; НЕ сидируется здесь — цепочка фолбэка в
--                             FR-12 подхватывает .env-значение, пока строка пуста/отсутствует.
create table if not exists app_settings (
    key        text primary key,
    value      jsonb not null,
    updated_at timestamptz not null default now()
);

insert into app_settings (key, value) values
    ('scoring_weights', '{
        "salary": 25,
        "work_format": 25,
        "grade_match": 20,
        "role_content": 20,
        "burnout": 10
    }'::jsonb),
    ('company_adjustments', '[
        {
            "match": ["сбербанк", "сбер ", "работа в сбере", "работа в сбер", "сбера", "сбер для it"],
            "delta": -7,
            "reason": "экосистема Сбер (риск выгорания)",
            "cap": null
        },
        {
            "match": ["vk ", "vk.com", "вконтакт", "head of ai", "vk tech"],
            "delta": -15,
            "reason": "работодатель VK (blocklist)",
            "cap": 0.4
        },
        {
            "match": ["яндекс", "yandex"],
            "delta": -3,
            "reason": "Яндекс (много этапов / fallback)",
            "cap": null
        },
        {
            "match": ["государствен", "министерств", "рниму", "унiversitet", "университет", "вуз", "федеральное государствен", "государственное автоном", "пирогов"],
            "delta": -12,
            "reason": "госсектор / вуз",
            "cap": null
        },
        {
            "match": ["гпх", "договор гпх", "договор с ип", "оформление: договор гпх"],
            "delta": -8,
            "reason": "оформление ГПХ / ИП",
            "cap": null
        },
        {
            "match": ["medical imaging", "компьютерное зрение", "dicom", "miccai", "midl", "медицинск", "мрт", "рентген", "computer vision"],
            "delta": -5,
            "reason": "домен CV / medical imaging",
            "cap": null
        },
        {
            "match": [" mpl", "язык mpl", "на mpl"],
            "delta": -5,
            "reason": "proprietary stack (MPL)",
            "cap": null
        }
    ]'::jsonb),
    ('salary_min_override', 'null'::jsonb),
    ('daily_cost_limit_usd', '5.0'::jsonb),
    ('daily_cost_hard_limit_usd', '10.0'::jsonb)
on conflict (key) do nothing;
