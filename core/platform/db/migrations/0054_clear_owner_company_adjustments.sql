-- 0054: снести сид owner-хардкода company_adjustments (Сбер/VK/Яндекс/гос/ГПХ/CV/MPL).
-- Предпочтения по компаниям — search_criteria.target_companies / avoid_companies в резюме.
-- Ручные правила AppSettings остаются power-user API; дефолт Python — [].
update app_settings
set value = '[]'::jsonb, updated_at = now()
where key = 'company_adjustments';
