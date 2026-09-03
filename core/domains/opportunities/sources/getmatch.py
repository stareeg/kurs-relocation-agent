"""Источник вакансий getmatch.ru.

Парсинг карточек в проде — в расширении (read-only DOM); здесь:
- канон извлечения numeric_id из ссылок;
- `VacancySource.parse` по HTML страницы вакансии (трёхуровневая стратегия:
  RSC Flight Stream → JSON-LD → regex DOM);
- `fetch` по URL/id — один GET, без форм/откликов.
"""

from __future__ import annotations

import json
import re
from html import unescape
from urllib.parse import urlparse

import httpx

from core.kernel.errors import InvalidInput
from core.kernel.vacancy import RawVacancy

# GM-9: извлечение numeric_id getmatch из текста/ссылки. Используется в боте
# (`bot_app/handlers/forwarded.py`), поэтому живёт в каноне источников, а не в хендлере бота.
# Исторические фолбэк-ключи уже приведены к канону `gm_{numeric_id}`.
_GETMATCH_URL_RE = re.compile(
    r"https?://(?:www\.)?(?:getmatch\.ru/vacancies/(\d+)|gm\.to/(\d+))",
    re.IGNORECASE,
)
_VACANCY_PATH_RE = re.compile(r"/vacancies/(\d+)(?:-|/?|$)", re.IGNORECASE)
_TAG_RE = re.compile(r"<[^>]+>")

# --- RSC Flight Stream ------------------------------------------------------------
_RSC_PUSH_RE = re.compile(r'self\.__next_f\.push\(\[1,"((?:[^"\\]|\\.)*)"\]\)')

# --- JSON-LD ----------------------------------------------------------------------
_LD_JSON_RE = re.compile(
    r'<script[^>]*type="application/ld\+json"[^>]*>(.*?)</script>',
    re.DOTALL,
)

# --- Fallback regex (сохранены как страховка, не удалять) -------------------------
_TITLE_RE = re.compile(
    r'<section[^>]*class="[^"]*b-vacancy-header[^"]*"[^>]*>.*?<h1[^>]*>(.*?)</h1>',
    re.DOTALL | re.IGNORECASE,
)
_TITLE_FALLBACK_RE = re.compile(r"<h1[^>]*>(.*?)</h1>", re.DOTALL | re.IGNORECASE)
_COMPANY_RE = re.compile(
    r'href="[^"]*/companies/[^"]*"[^>]*>(.*?)</a>',
    re.DOTALL | re.IGNORECASE,
)
_SALARY_RE = re.compile(
    r'<section[^>]*class="[^"]*b-vacancy-header[^"]*"[^>]*>.*?<h3[^>]*>(.*?)</h3>',
    re.DOTALL | re.IGNORECASE,
)
_DESC_RE = re.compile(
    r'<section[^>]*class="[^"]*b-vacancy-description[^"]*"[^>]*>(.*?)</section>',
    re.DOTALL | re.IGNORECASE,
)
_FORMAT_TAG_RE = re.compile(
    r'class="[^"]*tag_title[^"]*"[^>]*>\s*((?:удал|гибрид|офис|remote|hybrid)[^<]*)',
    re.IGNORECASE,
)
_AREA_TAG_RE = re.compile(
    r'class="[^"]*b-vacancy-locations[^"]*"[^>]*>.*?class="[^"]*tag_title[^"]*"[^>]*>\s*([^<]+)',
    re.DOTALL | re.IGNORECASE,
)

DEFAULT_HEADERS = {
    "User-Agent": (
        "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
        "AppleWebKit/537.36 (KHTML, like Gecko) Chrome/122.0.0.0 Safari/537.36"
    ),
    "Accept-Language": "ru-RU,ru;q=0.9,en-US;q=0.8,en;q=0.7",
    "Accept": "text/html,application/xhtml+xml",
}


def extract_getmatch_numeric_id_from_text(text: str | None) -> str | None:
    """Вернуть numeric_id getmatch-вакансии из её ссылки в тексте, или None.

    getmatch-бот шлёт ссылку вида `https://getmatch.ru/vacancies/{id}-{slug}` (полная)
    или короткую `https://gm.to/{id}`. Возвращаем чистый numeric (без префикса `gm_`),
    либо None — тогда вызывающий код использует фолбэк (digest/origin-ключ).
    """
    if not text:
        return None
    for match in _GETMATCH_URL_RE.finditer(text):
        numeric = match.group(1) or match.group(2)
        if numeric:
            return numeric
    return None


def _strip_html(fragment: str) -> str:
    text = _TAG_RE.sub(" ", fragment)
    text = unescape(text)
    text = text.replace("\u200b", "").replace("\u200c", "").replace("\u200d", "")
    text = text.replace("\ufeff", "").replace("\u200e", "").replace("\u200f", "")
    return re.sub(r"\s+", " ", text).strip()


def _canonical_vacancy_id(numeric: str) -> str:
    return f"gm_{numeric}"


def _numeric_from_query(query: str) -> str | None:
    q = query.strip()
    if q.startswith("gm_"):
        rest = q[3:]
        return rest if rest.isdigit() else None
    if q.isdigit():
        return q
    from_url = extract_getmatch_numeric_id_from_text(q)
    if from_url:
        return from_url
    match = _VACANCY_PATH_RE.search(q)
    return match.group(1) if match else None


# ============================================================================
# Layer 1: RSC Flight Stream
# ============================================================================


def _extract_flight_stream(html: str) -> str:
    """Извлечь конкатенированный Flight Stream из всех `self.__next_f.push([1,"..."])`."""
    return "".join(_RSC_PUSH_RE.findall(html))


def _extract_json_object(s: str, start: int) -> str | None:
    """Извлечь JSON-объект начиная с позиции `start`, балансируя фигурные скобки.

    Учитывает экранирование `\\"` внутри строк (не сбивает счёт скобок).
    Возвращает сырую строку объекта (включая открывающую `{`) или None, если
    баланс не сошёлся.
    """
    if start >= len(s) or s[start] != "{":
        return None
    depth = 0
    i = start
    while i < len(s):
        ch = s[i]
        if ch == "\\" and i + 1 < len(s):
            i += 2
            continue
        if ch == "{":
            depth += 1
        elif ch == "}":
            depth -= 1
            if depth == 0:
                return s[start : i + 1]
        i += 1
    return None


def _extract_initial_vacancy(html: str) -> dict | None:
    """Извлечь `initialVacancy` из RSC Flight Stream, или None.

    Ключ `initialVacancy` в потоке бывает с экранированными кавычками (`\\"initialVacancy\\":{`),
    поэтому ищем по подстроке имени поля, а первую `{` после него берём как начало объекта.
    """
    flight = _extract_flight_stream(html)
    key_idx = flight.find("initialVacancy")
    if key_idx < 0:
        return None
    brace_idx = flight.find("{", key_idx)
    if brace_idx < 0:
        return None
    raw = _extract_json_object(flight, brace_idx)
    if raw is None:
        return None
    # Внутри RSC-потока двойные кавычки экранированы как \"
    cleaned = raw.replace('\\"', '"')
    try:
        return json.loads(cleaned)
    except json.JSONDecodeError:
        return None


def _extract_work_format_from_rsc(location_items: list[dict]) -> str:
    """Вывести формат работы из location_items RSC.

    Приоритет: если есть remote — «удалённая», иначе первый не-remote, иначе пусто.
    """
    formats: list[str] = []
    for item in location_items:
        fmt = (item.get("format") or "").strip().lower()
        if fmt == "remote":
            formats.append("удалённая")
        elif fmt == "hybrid":
            formats.append("гибрид")
        elif fmt == "office":
            formats.append("офис")
    if "удалённая" in formats:
        return "удалённая"
    if formats:
        return formats[0]
    return ""


def _build_rsc_vacancy_text(data: dict) -> str:
    """Собрать связный текст вакансии из полей initialVacancy."""
    parts: list[str] = [data.get("position", "")]

    company = _rsc_company_name(data)
    if company:
        parts.append(f"Компания: {company}")

    salary = data.get("salary_description", "")
    if salary:
        parts.append(f"Зарплата: {salary}")

    locations = data.get("location_items", [])
    if locations:
        area = ", ".join(item.get("label", "") for item in locations if item.get("label"))
        if area:
            parts.append(f"Локация: {area}")

    fmt = _extract_work_format_from_rsc(locations)
    if fmt:
        parts.append(f"Формат работы: {fmt}")

    skills = [s.get("name", "") for s in data.get("skills_objects", [])]
    if skills:
        parts.append(f"Навыки: {', '.join(skills)}")

    specialization = data.get("specialization")
    if specialization:
        parts.append(f"Профиль: {specialization}")

    description = _strip_html(data.get("offer_description", ""))
    if description:
        parts.append("")
        parts.append(description)

    return "\n".join(parts)


def _rsc_company_name(data: dict) -> str:
    """Имя компании из RSC: скрытые компании → «Конфиденциально»."""
    company = data.get("company") or {}
    name = (company.get("name") or "").strip()
    if not name or name == "Название скрыто":
        return "Конфиденциально"
    return name


def map_rsc_to_raw_vacancy(data: dict, *, url: str = "") -> RawVacancy:
    """Маппинг `initialVacancy` → `RawVacancy`."""
    numeric = str(data.get("id", ""))
    vacancy_id = _canonical_vacancy_id(numeric) if numeric else ""
    locations: list[dict] = data.get("location_items", [])

    return RawVacancy(
        vacancy_id=vacancy_id,
        url=url or f"https://getmatch.ru/vacancies/{numeric}",
        title=data.get("position", ""),
        company=_rsc_company_name(data),
        text=_build_rsc_vacancy_text(data),
        salary_text=data.get("salary_description", ""),
        area=", ".join(item.get("label", "") for item in locations if item.get("label")),
        work_format=_extract_work_format_from_rsc(locations),
        source="getmatch",
        skills=[s["name"] for s in data.get("skills_objects", [])],
        specialization=data.get("specialization"),
        seniority=(data.get("seniorities") or [None])[0],
    )


# ============================================================================
# Layer 2: JSON-LD Fallback
# ============================================================================


def _extract_jsonld_jobposting(html: str) -> dict | None:
    """Извлечь Schema.org `JobPosting` из JSON-LD-скриптов, или None."""
    for match in _LD_JSON_RE.finditer(html):
        try:
            data = json.loads(match.group(1))
        except json.JSONDecodeError:
            continue
        if isinstance(data, dict) and data.get("@type") == "JobPosting":
            return data
    return None


def _extract_work_format_from_jsonld(data: dict) -> str:
    """Формат работы из JSON-LD: `jobLocationType` или `employmentType`."""
    loc_type = (data.get("jobLocationType") or "").strip()
    if loc_type == "TELECOMMUTE":
        return "удалённая"
    return ""


def _extract_area_from_jsonld(data: dict) -> str:
    """Города из JSON-LD `jobLocation[].address.addressLocality`."""
    locations = data.get("jobLocation", [])
    if isinstance(locations, dict):
        locations = [locations]
    parts: list[str] = []
    for loc in locations:
        if isinstance(loc, dict):
            addr = loc.get("address") or {}
            if isinstance(addr, dict):
                city = addr.get("addressLocality", "")
                if city:
                    parts.append(str(city))
    return ", ".join(parts)


def _extract_salary_from_jsonld(data: dict) -> str:
    """Собрать строку зарплаты из baseSalary JSON-LD."""
    salary = data.get("baseSalary") or {}
    if not isinstance(salary, dict):
        return ""

    value = salary.get("value")
    if isinstance(value, dict):
        mn = value.get("minValue")
        mx = value.get("maxValue")
    else:
        mn = salary.get("minValue")
        mx = salary.get("maxValue")

    currency = salary.get("currency", "")
    if mn is not None and mx is not None:
        return f"{mn} — {mx} {currency}".strip()
    if mn is not None:
        return f"от {mn} {currency}".strip()
    if mx is not None:
        return f"до {mx} {currency}".strip()
    return ""


def _build_jsonld_vacancy_text(data: dict) -> str:
    """Собрать связный текст вакансии из JSON-LD `JobPosting`."""
    parts: list[str] = [data.get("title", "")]

    org = data.get("hiringOrganization") or {}
    company = (org.get("name") or "").strip() if isinstance(org, dict) else ""
    if company:
        parts.append(f"Компания: {company}")

    salary = _extract_salary_from_jsonld(data)
    if salary:
        parts.append(f"Зарплата: {salary}")

    area = _extract_area_from_jsonld(data)
    if area:
        parts.append(f"Локация: {area}")

    fmt = _extract_work_format_from_jsonld(data)
    if fmt:
        parts.append(f"Формат работы: {fmt}")

    description = _strip_html(data.get("description", ""))
    if description:
        parts.append("")
        parts.append(description)

    return "\n".join(parts)


def map_jsonld_to_raw_vacancy(data: dict, *, url: str = "") -> RawVacancy:
    """Маппинг JSON-LD `JobPosting` → `RawVacancy`."""
    org = data.get("hiringOrganization") or {}
    company = (org.get("name") or "").strip() if isinstance(org, dict) else ""

    return RawVacancy(
        vacancy_id="",
        url=url,
        title=data.get("title", ""),
        company=company,
        text=_build_jsonld_vacancy_text(data),
        salary_text=_extract_salary_from_jsonld(data),
        area=_extract_area_from_jsonld(data),
        work_format=_extract_work_format_from_jsonld(data),
        source="getmatch",
    )


# ============================================================================
# Основная точка входа: трёхуровневая стратегия
# ============================================================================


def parse_getmatch_vacancy_html(html: str, *, url: str = "") -> RawVacancy:
    """Страница вакансии getmatch → RawVacancy. Три уровня извлечения.

    1. RSC Flight Stream `initialVacancy` — максимально богатый структурированный JSON.
    2. JSON-LD `JobPosting` — SEO-контракт, меньше полей, но стабильный.
    3. regex DOM — текущая реализация, страховка на случай если оба верхних слоя упали.
    """
    if not (html or "").strip():
        raise InvalidInput("пустой HTML вакансии getmatch", code="vacancy_parse")

    # Layer 1: RSC Flight Stream
    try:
        rsc = _extract_initial_vacancy(html)
        if rsc:
            return map_rsc_to_raw_vacancy(rsc, url=url)
    except Exception:
        pass  # fall through

    # Layer 2: JSON-LD
    try:
        ld = _extract_jsonld_jobposting(html)
        if ld:
            return map_jsonld_to_raw_vacancy(ld, url=url)
    except Exception:
        pass

    # Layer 3: regex DOM (старая реализация)
    return _parse_getmatch_vacancy_html_regex(html, url=url)


def _parse_getmatch_vacancy_html_regex(html: str, *, url: str = "") -> RawVacancy:
    """Страница вакансии getmatch → RawVacancy (regex DOM, запасной вариант)."""
    if not (html or "").strip():
        raise InvalidInput("пустой HTML вакансии getmatch", code="vacancy_parse")

    numeric = _numeric_from_query(url) or extract_getmatch_numeric_id_from_text(html)
    if numeric is None:
        path_m = _VACANCY_PATH_RE.search(html)
        numeric = path_m.group(1) if path_m else None

    title_m = _TITLE_RE.search(html) or _TITLE_FALLBACK_RE.search(html)
    title = _strip_html(title_m.group(1)) if title_m else ""

    company_m = _COMPANY_RE.search(html)
    company = _strip_html(company_m.group(1)) if company_m else ""

    salary_m = _SALARY_RE.search(html)
    salary_text = _strip_html(salary_m.group(1)) if salary_m else ""

    area_m = _AREA_TAG_RE.search(html)
    area = _strip_html(area_m.group(1)) if area_m else ""

    fmt_m = _FORMAT_TAG_RE.search(html)
    work_format = _strip_html(fmt_m.group(1)) if fmt_m else ""

    desc_m = _DESC_RE.search(html)
    description = _strip_html(desc_m.group(1)) if desc_m else ""

    if not title and not description and not numeric:
        raise InvalidInput(
            "не удалось разобрать страницу вакансии getmatch",
            code="vacancy_parse",
        )

    vacancy_id = _canonical_vacancy_id(numeric) if numeric else ""
    vacancy_url = url.strip()
    if not vacancy_url and numeric:
        vacancy_url = f"https://getmatch.ru/vacancies/{numeric}"

    parts = [
        title,
        f"Компания: {company}" if company else "",
        f"Зарплата: {salary_text}" if salary_text else "",
        f"Локация: {area}" if area else "",
        f"Формат работы: {work_format}" if work_format else "",
    ]
    if description:
        parts.append("")
        parts.append(description)
    text = "\n".join(p for p in parts if p).strip()

    return RawVacancy(
        vacancy_id=vacancy_id,
        url=vacancy_url,
        title=title,
        company=company,
        text=text,
        salary_text=salary_text,
        area=area,
        work_format=work_format,
        source="getmatch",
    )


class GetmatchVacancySource:
    """Реализация `VacancySource` для getmatch.ru."""

    name = "getmatch"

    async def fetch(self, query: str) -> list[RawVacancy]:
        q = (query or "").strip()
        if not q:
            raise InvalidInput("пустой запрос источника getmatch", code="vacancy_fetch")

        numeric = _numeric_from_query(q)
        if numeric is None:
            raise InvalidInput(
                "ожидается URL/id вакансии getmatch (gm_{id})",
                code="vacancy_fetch",
            )

        # Если в запросе уже полный URL getmatch — ходим по нему; иначе собираем канон.
        parsed = urlparse(q)
        if parsed.scheme in ("http", "https") and "getmatch.ru" in parsed.netloc:
            url = q
        else:
            url = f"https://getmatch.ru/vacancies/{numeric}"

        async with httpx.AsyncClient(
            headers=DEFAULT_HEADERS,
            timeout=25.0,
            follow_redirects=True,
        ) as client:
            response = await client.get(url)
            response.raise_for_status()
            html = response.text
        return [parse_getmatch_vacancy_html(html, url=url)]

    def parse(self, html: str) -> RawVacancy:
        return parse_getmatch_vacancy_html(html)


__all__ = [
    "GetmatchVacancySource",
    "extract_getmatch_numeric_id_from_text",
    "parse_getmatch_vacancy_html",
]
