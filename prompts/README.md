# Рантайм-промпты системы

Каталоги = имена доменов:

| Каталог | Домен |
| --- | --- |
| `opportunities/` | скоринг, instructions, weights_spec, judges |
| `preparation/screening/`, `preparation/legend/`, … | скрининг, легенда, технички |
| `profile/` | резюме / гэпы / усиление |
| `pipeline/` | HR-черновики, воронка, cover letter |
| `offers/` | парсинг / сравнение / торг |
| `market/` | ситуация, narrative |
| `assistant/` | чат |

Правка файла меняет поведение без изменений Python. Модель выбирается тиром через
`LlmFeature` в `core/domains/<domain>/llm.py` (опционально `AGENT_TIER_OVERRIDES` в `.env`);
путь к промпту — там же (не в `CoreSettings` / не через `*_PROMPT_PATH` — R-40/A-06).

Спецификация весов скоринга — `opportunities/weights_spec.yaml` (держи в согласии с
`opportunities/instructions.md` и `core/domains/opportunities/score_breakdown.py`).

Существование всех задекларированных путей — `tests/test_settings_paths_exist.py`.

Дев-промптам, черновикам и экспериментам здесь не место — им в `plans/`.
