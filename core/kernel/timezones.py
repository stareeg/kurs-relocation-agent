"""География кандидата: город → страна и IANA-зона, пересечение рабочих часов.

Чистый kernel (stdlib + zoneinfo, без I/O). Единственная деривация географии кандидата:
страна в резюме (`work_countries`) заполняется отсюда, поэтому обратного фолбэка
«страна → зона» нет — он замкнул бы вывод сам на себя.

Справочник — референс-таблица уровня GRADE_SCALE, не хардкод владельца: ключи приходят
из резюме, ни один город не привилегирован. Он же питает подсказки поля «Город проживания»
на холодном старте, пока в системе нет ни одной оценённой вакансии.
"""

from __future__ import annotations

from datetime import UTC, date, datetime, time
from typing import NamedTuple
from zoneinfo import ZoneInfo, ZoneInfoNotFoundError

WORK_DAY_LOCAL: tuple[int, int] = (10, 19)  # рабочий день кандидата, локально

REGION_WORK_HOURS: dict[str, tuple[str, int, int]] = {
    "EMEA": ("Europe/Berlin", 9, 18),
    "UK": ("Europe/London", 9, 18),
    "US-East": ("America/New_York", 9, 18),
    "US-West": ("America/Los_Angeles", 9, 18),
    "APAC": ("Asia/Singapore", 9, 18),
}

UNKNOWN_CITY_HINT = "Страну и часовой пояс не определили — выберите ближайший город из списка"


class CityGeo(NamedTuple):
    country: str  # «Россия» — как в справочнике lib/countries.ts
    timezone: str  # IANA, «Europe/Moscow»


# (канон, страна, IANA, *алиасы). Алиасы только для распознавания, в подсказки не попадают.
_CITY_ROWS: tuple[tuple[str, ...], ...] = (
    ("Москва", "Россия", "Europe/Moscow", "Moscow"),
    (
        "Санкт-Петербург",
        "Россия",
        "Europe/Moscow",
        "СПб",
        "Питер",
        "Saint Petersburg",
        "St. Petersburg",
        "St Petersburg",
    ),
    ("Новосибирск", "Россия", "Asia/Novosibirsk", "Novosibirsk"),
    ("Екатеринбург", "Россия", "Asia/Yekaterinburg", "Yekaterinburg", "Ekaterinburg"),
    ("Казань", "Россия", "Europe/Moscow", "Kazan"),
    ("Нижний Новгород", "Россия", "Europe/Moscow", "Nizhny Novgorod"),
    ("Челябинск", "Россия", "Asia/Yekaterinburg", "Chelyabinsk"),
    ("Самара", "Россия", "Europe/Samara", "Samara"),
    ("Ростов-на-Дону", "Россия", "Europe/Moscow", "Rostov-on-Don", "Rostov"),
    ("Уфа", "Россия", "Asia/Yekaterinburg", "Ufa"),
    ("Красноярск", "Россия", "Asia/Krasnoyarsk", "Krasnoyarsk"),
    ("Воронеж", "Россия", "Europe/Moscow", "Voronezh"),
    ("Пермь", "Россия", "Asia/Yekaterinburg", "Perm"),
    ("Краснодар", "Россия", "Europe/Moscow", "Krasnodar"),
    ("Владивосток", "Россия", "Asia/Vladivostok", "Vladivostok"),
    ("Калининград", "Россия", "Europe/Kaliningrad", "Kaliningrad"),
    ("Сочи", "Россия", "Europe/Moscow", "Sochi"),
    ("Тюмень", "Россия", "Asia/Yekaterinburg", "Tyumen"),
    ("Иркутск", "Россия", "Asia/Irkutsk", "Irkutsk"),
    ("Томск", "Россия", "Asia/Tomsk", "Tomsk"),
    ("Минск", "Беларусь", "Europe/Minsk", "Minsk"),
    ("Алматы", "Казахстан", "Asia/Almaty", "Almaty"),
    ("Астана", "Казахстан", "Asia/Almaty", "Astana", "Нур-Султан", "Nur-Sultan"),
    ("Тбилиси", "Грузия", "Asia/Tbilisi", "Tbilisi"),
    ("Ереван", "Армения", "Asia/Yerevan", "Yerevan"),
    ("Баку", "Азербайджан", "Asia/Baku", "Baku"),
    ("Ташкент", "Узбекистан", "Asia/Tashkent", "Tashkent"),
    ("Бишкек", "Киргизия", "Asia/Bishkek", "Bishkek"),
    ("Кишинёв", "Молдова", "Europe/Chisinau", "Кишинев", "Chisinau", "Kishinev"),
    ("Киев", "Украина", "Europe/Kyiv", "Kyiv", "Kiev"),
    ("Лиссабон", "Португалия", "Europe/Lisbon", "Lisbon"),
    ("Барселона", "Испания", "Europe/Madrid", "Barcelona"),
    ("Берлин", "Германия", "Europe/Berlin", "Berlin"),
    ("Амстердам", "Нидерланды", "Europe/Amsterdam", "Amsterdam"),
    ("Варшава", "Польша", "Europe/Warsaw", "Warsaw"),
    ("Прага", "Чехия", "Europe/Prague", "Prague"),
    ("Белград", "Сербия", "Europe/Belgrade", "Belgrade"),
    ("Стамбул", "Турция", "Europe/Istanbul", "Istanbul"),
    ("Дубай", "ОАЭ", "Asia/Dubai", "Dubai"),
    ("Лимассол", "Кипр", "Asia/Nicosia", "Limassol"),
    ("Бангкок", "Таиланд", "Asia/Bangkok", "Bangkok"),
    ("Хошимин", "Вьетнам", "Asia/Ho_Chi_Minh", "Ho Chi Minh", "Saigon", "Сайгон"),
    ("Сингапур", "Сингапур", "Asia/Singapore", "Singapore"),
    ("Тель-Авив", "Израиль", "Asia/Jerusalem", "Tel Aviv"),
    ("Лондон", "Великобритания", "Europe/London", "London"),
    ("Нью-Йорк", "США", "America/New_York", "New York"),
    ("Буэнос-Айрес", "Аргентина", "America/Argentina/Buenos_Aires", "Buenos Aires"),
)


def normalize_city(city: str) -> str:
    """Канон ключа: trim, casefold, ё→е, схлопнутые пробелы. Пустая строка — не город."""
    return " ".join(city.strip().casefold().replace("ё", "е").split())


def _build_lookups() -> tuple[dict[str, CityGeo], dict[str, str], tuple[str, ...]]:
    geos: dict[str, CityGeo] = {}
    display: dict[str, str] = {}
    canon: list[str] = []
    for row in _CITY_ROWS:
        name, country, tz, *aliases = row
        geo = CityGeo(country, tz)
        keys = (name, *aliases)
        for raw in keys:
            geos[normalize_city(raw)] = geo
            display[normalize_city(raw)] = name
        canon.append(name)
    return geos, display, tuple(canon)


_CITY_GEO, _CITY_DISPLAY, _CITIES_REFERENCE = _build_lookups()


def city_geo(city: str) -> CityGeo | None:
    """Город → страна и часовой пояс. Нет совпадения — None (не угадываем)."""
    key = normalize_city(city)
    if not key:
        return None
    return _CITY_GEO.get(key)


def canonical_city_name(city: str) -> str | None:
    """Каноническое написание из справочника; неизвестный город — None."""
    key = normalize_city(city)
    if not key:
        return None
    return _CITY_DISPLAY.get(key)


def cities_reference() -> tuple[str, ...]:
    """Курируемый список городов для подсказок на холодном старте."""
    return _CITIES_REFERENCE


def utc_offset_label(tz_name: str, *, at: datetime | None = None) -> str:
    """Смещение IANA-зоны на момент `at` (по умолчанию сейчас), вид «UTC+3» / «UTC-5:00»."""
    try:
        tz = ZoneInfo(tz_name)
    except (ZoneInfoNotFoundError, KeyError, ValueError):
        return ""
    moment = at or datetime.now(UTC)
    offset = moment.astimezone(tz).utcoffset()
    if offset is None:
        return ""
    total_min = int(offset.total_seconds() // 60)
    hours, minutes = divmod(abs(total_min), 60)
    sign = "+" if total_min >= 0 else "-"
    if minutes:
        return f"UTC{sign}{hours}:{minutes:02d}"
    return f"UTC{sign}{hours}"


def utc_offset_minutes(tz_name: str, *, at: datetime | None = None) -> int:
    """Смещение IANA-зоны в минутах относительно UTC. Неизвестная зона → 0."""
    try:
        tz = ZoneInfo(tz_name)
    except (ZoneInfoNotFoundError, KeyError, ValueError):
        return 0
    moment = at or datetime.now(UTC)
    offset = moment.astimezone(tz).utcoffset()
    if offset is None:
        return 0
    return int(offset.total_seconds() // 60)


def overlap_hours(home_tz: str, region: str, *, day: date | None = None) -> int:
    """Часов пересечения рабочего дня кандидата с рабочим днём региона (0..9)."""
    spec = REGION_WORK_HOURS.get(region)
    if spec is None:
        return 0
    region_tz, r_start, r_end = spec
    c_start, c_end = WORK_DAY_LOCAL
    on = day or date.today()
    try:
        home = ZoneInfo(home_tz)
        remote = ZoneInfo(region_tz)
    except (ZoneInfoNotFoundError, KeyError, ValueError):
        return 0

    def _window(tz: ZoneInfo, start_h: int, end_h: int) -> tuple[datetime, datetime]:
        start = datetime.combine(on, time(start_h), tzinfo=tz).astimezone(UTC)
        end = datetime.combine(on, time(end_h), tzinfo=tz).astimezone(UTC)
        return start, end

    hs, he = _window(home, c_start, c_end)
    rs, re = _window(remote, r_start, r_end)
    begin = max(hs, rs)
    finish = min(he, re)
    if finish <= begin:
        return 0
    return int((finish - begin).total_seconds() // 3600)


def overlap_map(home_tz: str, *, day: date | None = None) -> dict[str, int]:
    """Регион → часы пересечения по всем REGION_WORK_HOURS."""
    if not home_tz.strip():
        return {}
    return {region: overlap_hours(home_tz, region, day=day) for region in REGION_WORK_HOURS}


def derived_work_countries(city: str, existing: list[str]) -> list[str] | None:
    """Страна из города + уже лежащее второе резидентство.

    None — город не распознан, existing не трогаем (не угадываем и не затираем).
    """
    geo = city_geo(city)
    if geo is None:
        return None
    extras = [c for c in existing if c != geo.country]
    return [geo.country, *extras]


def city_derived_line(city: str) -> str:
    """Часовой пояс рядом с полем города («UTC+3»). Пустой город — пустая строка."""
    if not city.strip():
        return ""
    geo = city_geo(city)
    if geo is None:
        return UNKNOWN_CITY_HINT
    return utc_offset_label(geo.timezone) or UNKNOWN_CITY_HINT


__all__ = [
    "UNKNOWN_CITY_HINT",
    "WORK_DAY_LOCAL",
    "REGION_WORK_HOURS",
    "CityGeo",
    "canonical_city_name",
    "cities_reference",
    "city_derived_line",
    "city_geo",
    "derived_work_countries",
    "normalize_city",
    "overlap_hours",
    "overlap_map",
    "utc_offset_label",
    "utc_offset_minutes",
]
