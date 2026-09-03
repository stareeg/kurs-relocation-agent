# Фикстуры getmatch.ru (RSC Flight Stream)

Снэпшоты страниц вакансий getmatch.ru для тестов RSC-парсера (Шаг 1 плана
`plans/getmatch_refactoring_plan.md`). Каждая страница — Next.js App Router,
`initialVacancy` лежит внутри `self.__next_f.push([1,"..."])`.

Полные снимки (с CSS/JS-ассетами) — в `plans/getmatch_integration/` (gitignored).
Здесь — только HTML, санитайзированный от персональных данных: email и `candidate.id`
заменены на `candidate@example.com` / `REDACTED`, имя, Telegram, фото и зарплата из профиля
кандидата — на выдуманные.

## Доступные фикстуры

| Файл | Сценарий | id | Компания | Зарплата |
| --- | --- | --- | --- | --- |
| `vacancy_full.html` | Полная вакансия: вилка, 6 навыков, remote | 35788 | Selecty (видимая) | `220 000 — 310 000 ₽/мес на руки` |
| `vacancy_hidden_company.html` | Скрытая компания + зарплата без вилки (`salary_hidden=true`, `salary_display_from/to=null`) + 8 локаций (hybrid+remote) + 10 навыков | 34714 | Название скрыто | `от 383 000 ₽/мес на руки` |
| `vacancy_applied.html` | Уже откликнулся (`application` заполнен) | 35788 | Selecty | как в `vacancy_full` |

## Покрытие краевых случаев плана

- **Видимая компания** → `vacancy_full.html` (`company.name == "Selecty"`,
  `industry`, `size`, `logotype` заполнены).
- **Скрытая компания** → `vacancy_hidden_company.html` (`company.name == "Название
  скрыто"`, `logotype/url/industry/size == null`) — маппится на «Конфиденциально».
- **Зарплата без вилки** → `vacancy_hidden_company.html`
  (`salary_hidden=true`, `salary_display_from/to == null`) — соответствует
  `test_parse_rsc_no_salary` из плана (8.2).
- **Несколько локаций / гибрид** → `vacancy_hidden_company.html` (8 `location_items`,
  форматы `remote` + `hybrid`) — покрывает релокацию/мультиформат.
- **Откликнулся** → `vacancy_applied.html` (`application.id`, `application.applied_at`).

## Чего пока нет (нужен живой getmatch)

- `vacancy_no_salary.html` — полностью без зарплаты (`salary_description` пуст /
  «По договорённости»). В текущих снэпшотах такой страницы не было; частично
  покрывается `vacancy_hidden_company.html` (null-поля вилки).
- `vacancy_archived.html` — снятая/архивная вакансия (`is_active == false`). Во всех
  снэпшотах `is_active == true`; снять живую архивную страницу.
- `vacancy_with_relocation.html` — отдельная фикстура релокации. Мультилокация уже
  покрыта `vacancy_hidden_company.html`.

## Схема initialVacancy

Документированная JSON-схема `initialVacancy` — в
`plans/getmatch_integration/_vacancy_schema.py` (gitignored, локальный анализ).
Скрипт извлечения — `plans/getmatch_integration/_extract_initial_vacancy.py`.

Ключевые поля для маппинга (см. план, Шаг 2/4): `position`, `company.{name,url}`,
`salary_description`, `salary_display_from/to`, `salary_currency`, `salary_taxes`,
`location_items[].{label,format}`, `offer_description`, `skills_objects[].name`,
`specialization`, `seniorities[]`, `cover_letter_required`, `published_at`, `id`,
`is_active`.
