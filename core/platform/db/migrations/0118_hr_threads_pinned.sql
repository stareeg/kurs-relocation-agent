-- 0118: закрепление диалогов в списке слева («Чаты») — небольшая кнопка под «Удалить».
alter table hr_threads
    add column if not exists pinned boolean not null default false;
