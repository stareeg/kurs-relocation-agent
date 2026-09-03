-- Детальный аудит балла резюме (writing/role_fit fixes) — JSON от LLM, переживает рестарт.
ALTER TABLE resume_score_history
    ADD COLUMN IF NOT EXISTS audit_json jsonb;
