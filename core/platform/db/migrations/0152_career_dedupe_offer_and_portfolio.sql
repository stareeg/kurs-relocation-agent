-- 0152_career_dedupe_offer_and_portfolio — Этап 1 плана редизайна «Карьеры»
-- (plans/career_redesign_2026_08_26.md). Владелец нашёл на живом проде: дубликаты офферов в
-- ленте и в «Достижениях» (два одинаковых оффера «МТС» подряд), и мусорные строки «Дубль
-- вакансии» в ленте карьеры. Обе находки — решённые владельцем развилки плана (2026-08-26):
-- дубли чистим сейчас одним разовым SQL, «Дубль вакансии» убираем совсем (career/events.py
-- в этом же заходе отписан от `VacancyDeduplicated`).
--
-- Порядок обязателен: сначала чистим существующие данные, потом ставим уникальный индекс —
-- иначе `create unique index` упадёт на уже накопленных дублях.
--
-- Дедуп НАМЕРЕННО не распространяется на kind='stage'/'other'(разборы)/'search_mode'/
-- 'search_track': там `source_ref` сегодня законно переиспользуется между РАЗНЫМИ occurrence
-- (у одной вакансии много legit-строк "stage" на разные этапы с одним и тем же source_ref =
-- vacancy_id; у одной вакансии бывает несколько разборов с одним и тем же source_ref). Наивный
-- unique index там молча съел бы настоящую историю вместо дублей — хуже проблемы, которую
-- чиним. Ни одного подтверждённого дубля по этим kind не найдено — см. план, раздел
-- «Осознанно НЕ делаем в этом заходе».

-- 1) «Дубль вакансии» — технический сигнал импорта, не карьерное событие. Решение владельца —
--    убрать совсем, включая уже накопленную историю.
delete from career_timeline where payload ->> 'event' = 'VacancyDeduplicated';

-- 2) Дубли строк "Оффер" в ленте: оставить самую раннюю запись на (account_id, source_ref).
delete from career_timeline t
using (
    select id, row_number() over (
        partition by account_id, source_ref
        order by occurred_at, id
    ) as rn
    from career_timeline
    where kind = 'offer' and source_ref <> ''
) dup
where t.id = dup.id and dup.rn > 1;

-- 3) Дубли элементов портфолио (резюме/разбор/оффер — у каждого генератора черновика source_ref
--    уже привязан к конкретному occurrence, поэтому дедуп безопасен для всей таблицы целиком).
delete from career_portfolio_items p
using (
    select id, row_number() over (
        partition by account_id, source_ref
        order by created_at, id
    ) as rn
    from career_portfolio_items
    where source_ref <> ''
) dup
where p.id = dup.id and dup.rn > 1;

-- Защита на будущее: повторная публикация OfferReceived / повторный черновик по тому же
-- офферу/разбору/резюме-блоку больше не создаёт вторую строку (insert идёт через
-- `on conflict ... do nothing`, core/domains/career/repo.py).
create unique index career_timeline_offer_source_ref_uidx
    on career_timeline (account_id, source_ref)
    where kind = 'offer' and source_ref <> '';

create unique index career_portfolio_items_source_ref_uidx
    on career_portfolio_items (account_id, source_ref)
    where source_ref <> '';
