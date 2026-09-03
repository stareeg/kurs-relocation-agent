# domains

Доменные пакеты продукта. Каждый домен — одна бизнес-область.

Форма: `models` / `service` / `repo` / `llm` / `events` / `README` (по надобности;
`events.py` обязателен у всех — собирается в `core/app/subscriptions.py`).

Сейчас **9** bounded contexts:

| Домен | LLM | Заметка |
| --- | --- | --- |
| `assistant` | да | чат SSE, заметки, вложения |
| `profile` | да | резюме, SearchProfile, ATS |
| `opportunities` | да | скоринг, доска, discovery |
| `pipeline` | да | воронка, HR, cover letter |
| `preparation` | да | скрининг / технички |
| `offers` | да | офферы |
| `market` | да | пульс / ситуация / калибровка |
| `career` | нет | лента, факты, портфолио, трек, дружба (API) |
| `multiplayer` | да | «Мультиплеер»; три модели: `MODEL_MULTIPLAYER` + `_ACTOR` + `_ARBITER` |

Карта «фича → домен» и удалённое (не возвращать) — в `docs/ARCHITECTURE.md` и корневом
`CLAUDE.md`.
