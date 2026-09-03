"""Кросс-доменные сценарии.

Здесь живёт то, что не принадлежит одному домену: разговор вакансии (pipeline + opportunities +
preparation), чат подготовки (preparation + assistant), оффер (offers + market + opportunities +
profile), сопроводительное (opportunities + pipeline + preparation), кандидаты компаний
(opportunities + profile), Q&A по вакансии (preparation + pipeline), разбор собеса
(preparation + opportunities).

Правило раскладки: сценарий переезжает сюда, только если трогает **два и более** домена. Если
логика целиком внутри одного контекста — её место в `domains/<name>/service.py` (или
`domains/<name>/scenarios.py`), а не тут.

Роутеры зовут эти функции и не содержат логики: валидация входа, вызов сценария, `to_http` на
доменной ошибке. Сценарии не знают про FastAPI и бросают `core.kernel.errors.*`.
"""

from __future__ import annotations

__all__: list[str] = []
