-- Веса скоринга v2: burnout → management, добавлен company (сумма 100).
-- Старые UI/API ожидали 5 ключей; канон теперь 20/20/15/15/15/15.

UPDATE app_settings
SET
    value = '{
        "salary": 20,
        "work_format": 20,
        "grade_match": 15,
        "role_content": 15,
        "management": 15,
        "company": 15
    }'::jsonb,
    updated_at = now()
WHERE key = 'scoring_weights';
