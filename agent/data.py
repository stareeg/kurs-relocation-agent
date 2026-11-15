"""Синтетические данные для демо агента.

Курс разрешает синтетические и открытые данные, реальные клиентские — нет. Здесь только
придуманные вакансии и правила стран, без персональных данных.
"""

from __future__ import annotations

from typing import Final

# Вакансии: id, роль, страна, зарплата в евро в месяц, удалёнка, форма договора.
VACANCIES: Final[tuple[dict[str, object], ...]] = (
    {
        "id": "v01",
        "title": "Senior Python Engineer",
        "company": "Nordwind Labs",
        "role": "backend",
        "country": "Польша",
        "salary_eur": 4500,
        "remote": True,
        "contract": "B2B",
    },
    {
        "id": "v02",
        "title": "Backend Developer (Go)",
        "company": "Wisla Systems",
        "role": "backend",
        "country": "Польша",
        "salary_eur": 3800,
        "remote": False,
        "contract": "UoP",
    },
    {
        "id": "v03",
        "title": "Platform Engineer",
        "company": "Dunav Cloud",
        "role": "backend",
        "country": "Сербия",
        "salary_eur": 3200,
        "remote": True,
        "contract": "B2B",
    },
    {
        "id": "v04",
        "title": "Data Engineer",
        "company": "Morava Analytics",
        "role": "data",
        "country": "Сербия",
        "salary_eur": 3600,
        "remote": True,
        "contract": "B2B",
    },
    {
        "id": "v05",
        "title": "Frontend Engineer (React)",
        "company": "Spree Digital",
        "role": "frontend",
        "country": "Германия",
        "salary_eur": 4200,
        "remote": True,
        "contract": "UoP",
    },
    {
        "id": "v06",
        "title": "QA Automation Engineer",
        "company": "Vltava Quality",
        "role": "qa",
        "country": "Чехия",
        "salary_eur": 2800,
        "remote": True,
        "contract": "B2B",
    },
    {
        "id": "v07",
        "title": "Backend Engineer (Python)",
        "company": "Prague Data Works",
        "role": "backend",
        "country": "Чехия",
        "salary_eur": 3400,
        "remote": True,
        "contract": "B2B",
    },
    {
        "id": "v08",
        "title": "Staff Backend Engineer",
        "company": "Berlin Fintech",
        "role": "backend",
        "country": "Германия",
        "salary_eur": 5200,
        "remote": False,
        "contract": "UoP",
    },
)

# Правила страны для гражданина России. Условные, для демонстрации; не юридическая консультация.
COUNTRY_RULES: Final[dict[str, dict[str, str]]] = {
    "Польша": {
        "visa": "Рабочая виза или ВНЖ по работе; для B2B часто нужен ВНЖ по бизнесу",
        "work_permit": (
            "Разрешение на работу привязано к работодателю (UoP) или к своему делу (B2B)"
        ),
        "taxes": "PIT 12–32% или линейный 19%; ZUS при UoP, B2B — своим взносом",
        "note": (
            "Польша не требует отдельного разрешения на работу для граждан ЕС, "
            "для граждан РФ — требует"
        ),
    },
    "Сербия": {
        "visa": "ВНЖ по работе оформляет работодатель; безвизовый въезд до 30 дней",
        "work_permit": "Единое разрешение на пребывание и работу (dozvola za rad)",
        "taxes": "Подоходный 10% и взносы; для фрилансеров есть режим с фиксированным взносом",
        "note": "Требование к зарплате иностранца — не ниже средней по региону",
    },
    "Германия": {
        "visa": "Голубая карта ЕС при зарплате выше порога или рабочая виза",
        "work_permit": "Разрешение привязано к работодателю; смена работы — новое согласование",
        "taxes": "Подоходный 14–45% плюс взносы; B2B-схемы для фрилансеров ограничены",
        "note": "Порог голубой карты меняется ежегодно, проверяйте актуальный",
    },
    "Чехия": {
        "visa": "Рабочая виза или карта сотрудника; сроки очередей длинные",
        "work_permit": "Разрешение на работу и пребывание оформляются вместе",
        "taxes": "Подоходный 15–23%; для B2B нужен статус ИП",
        "note": "Квоты на визы зависят от консульства, планируйте заранее",
    },
}

MAX_RESULT_ITEMS: Final = 5
