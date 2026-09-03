-- 0142_accounts_operator_fields — заметка оператора и причина отключения
-- (plans/admin_panel_2026_08_25.md Этап 4.6). Без этих колонок через полгода «почему
-- этот выключен» неотвечаемый вопрос; заметка живёт только в админ-витрине и не должна
-- утекать в /auth/status и /api/settings.
alter table accounts
    add column if not exists note text,
    add column if not exists disabled_at timestamptz,
    add column if not exists disabled_reason text;
