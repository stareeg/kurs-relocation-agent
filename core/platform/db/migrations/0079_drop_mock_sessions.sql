-- 0079_drop_mock_sessions — F-16: тренажёр (мок-собес) удалён как осиротевшая ручка
-- (`/api/mock/*` не звал ни веб, ни расширение, ни бот). Уровень владения темой
-- (MockMastery/MockCompetency) остался — общая карта компетенций разбора собеса (JS-14).

drop table if exists mock_sessions;
