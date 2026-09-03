-- 0094_search_state_retire_offer_endgame — ST-01 revision: «оффер на руках» как ручной
-- переключатель режима поиска был лишним (наличие принятого оффера и так видно по воронке/
-- разделу «Офферы») и сбивал с толку — режим должен отвечать только на «насколько активно
-- ищу», а не дублировать факт, который система знает сама. Канон сузился до active/passive.
--
-- Существующие записи журнала с mode/prev_mode = 'offer_endgame' переносим в 'passive' —
-- ближайший валидный смысл (уже не активный поиск), а не молча ломаем чтение истории типом
-- SearchMode, который больше не принимает старое значение.

update search_state_log set mode = 'passive' where mode = 'offer_endgame';
update search_state_log set prev_mode = 'passive' where prev_mode = 'offer_endgame';

alter table search_state_log drop constraint if exists search_state_log_mode_check;
alter table search_state_log add constraint search_state_log_mode_check
    check (mode in ('active', 'passive'));

alter table search_state_log drop constraint if exists search_state_log_prev_mode_check;
alter table search_state_log add constraint search_state_log_prev_mode_check
    check (prev_mode is null or prev_mode in ('active', 'passive'));
