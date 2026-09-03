-- 0045_interview_stage_source — RD-20: этап, попавший в цепочку из HR-переписки (не руками), несёт
-- ссылку на реплику-источник — бейдж «из переписки» в степпере, клик ведёт в диалог вакансии
-- (доверие к авто-данным через проверяемость, тот же принцип, что клиент-diff легенды).
-- on delete set null — удаление сообщения (переимпорт дампа) не должно ронять уже начатый этап.

alter table interview_stages
    add column if not exists source_message_id bigint references hr_messages (id) on delete set null;
