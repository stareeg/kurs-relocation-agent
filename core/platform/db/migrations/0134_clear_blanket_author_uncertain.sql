-- 0134_clear_blanket_author_uncertain — LLM ставила author_uncertain на всю пачку импорта,
-- даже когда стороны уже различены (кейс Магнит/Ирина, 2026-08-24). Снимаем флаг у тредов,
-- где все hr-реплики помечены uncertain, но есть обе стороны.

update hr_messages m
set author_uncertain = false
where m.author_uncertain
  and m.kind in ('hr_in', 'hr_out')
  and exists (
    select 1 from hr_messages a
    where a.thread_id = m.thread_id and a.kind = 'hr_in'
  )
  and exists (
    select 1 from hr_messages b
    where b.thread_id = m.thread_id and b.kind = 'hr_out'
  )
  and not exists (
    select 1 from hr_messages c
    where c.thread_id = m.thread_id
      and c.kind in ('hr_in', 'hr_out')
      and not c.author_uncertain
  );
