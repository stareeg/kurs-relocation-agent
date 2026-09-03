"""Источник вакансий career.habr.com.

Парсинг карточек в проде — в расширении (read-only DOM + SSR-JSON); здесь:
- канон извлечения numeric_id из ссылок;
- `VacancySource.parse` по HTML страницы вакансии (SSR-JSON primary, JSON-LD fallback);
- `fetch` по URL/id — один GET, без форм/откликов;
- детерминированный маппинг грейда Хабр → относительная шкала.

Дееп-дайв реального HTML показал:
- Хост — career.habr.com, не habr.com.
- Primary источник данных — SSR-JSON в `<script type="application/json" data-ssr-state="true">`.
- JSON-LD — только fallback (Cloudflare-страница или SPA без гидратации).
- Net/gross нет в структурированных данных; salary.formatted проксируется строкой.
- Квалификация — enum: 1=Intern, 3=Junior, 4=Middle, 5=Senior, 6=Lead.
"""

from __future__ import annotations

import json
import re
from html import unescape
from typing import Any
from urllib.parse import urlparse

import httpx

from core.kernel.errors import InvalidInput
from core.kernel.vacancy import RawVacancy

# Regex для извлечения numeric_id Хабр из текста/ссылки.
_HABR_URL_RE = re.compile(
    r"https?://(?:www\.)?career\.habr\.com/vacancies/(\d+)",
    re.IGNORECASE,
)
_HABR_VACANCY_PATH_RE = re.compile(r"/vacancies/(\d+)", re.IGNORECASE)

# SSR-JSON: <script type="application/json" data-ssr-state="true">{...}</script>
_SSR_JSON_RE = re.compile(
    r'<script[^>]*data-ssr-state="true"[^>]*>(.*?)</script>',
    re.DOTALL | re.IGNORECASE,
)
# JSON-LD fallback: <script type="application/ld+json">{...}</script>
_JSON_LD_RE = re.compile(
    r'<script\s+type="application/ld\+json"[^>]*>(.*?)</script>',
    re.DOTALL | re.IGNORECASE,
)

_TAG_RE = re.compile(r"<[^>]+>")

DEFAULT_HEADERS = {
    "User-Agent": (
        "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
        "AppleWebKit/537.36 (KHTML, like Gecko) Chrome/122.0.0.0 Safari/537.36"
    ),
    "Accept-Language": "ru-RU,ru;q=0.9,en-US;q=0.8,en;q=0.7",
    "Accept": "text/html,application/xhtml+xml",
}

# Лестница грейдов Хабр (квалификация): 1=Intern, 3=Junior, 4=Middle, 5=Senior, 6=Lead.
# Значения 2 и 7+ отсутствуют в данных Хабр (C-level/Teamlead — нет отдельных enum).
_HABR_LADDER: tuple[str, ...] = ("Intern", "Junior", "Middle", "Senior", "Lead")


def extract_habr_numeric_id_from_text(text: str | None) -> str | None:
    """Вернуть numeric_id habr-вакансии из ссылки в тексте, или None.

    Хабр-ссылка: `https://career.habr.com/vacancies/{id}`.
    Возвращаем чистый numeric (без префикса `habr_`).
    """
    if not text:
        return None
    match = _HABR_URL_RE.search(text)
    if match:
        return match.group(1)
    return None


def _canonical_vacancy_id(numeric: str) -> str:
    """Каноничный vacancy_id: `habr_{numeric}` — как `gm_` для getmatch."""
    return f"habr_{numeric}"


def map_habr_qualification(qualification: str, target: str) -> str:
    """Детерминированный маппинг грейда Хабр → относительная шкала.

    `qualification` — строка из SSR-JSON (Intern/Junior/Middle/Senior/Lead).
    `target` — из `SearchProfile.grades` (НЕ хардкод); если target не в _HABR_LADDER —
    по умолчанию Senior (индекс 3, консервативный фолбэк).

    Возвращает одно из: match / above / slightly_below / far_below / off_profile.
    `off_profile` — только если qualification не в _HABR_LADDER (неизвестное значение).
    """
    if qualification not in _HABR_LADDER:
        return "off_profile"
    q = _HABR_LADDER.index(qualification)
    t = _HABR_LADDER.index(target) if target in _HABR_LADDER else 3  # default: Senior
    if q == t:
        return "match"
    if q > t:
        return "above"
    if q == t - 1:
        return "slightly_below"
    return "far_below"


def _strip_html(fragment: str) -> str:
    """Убрать HTML-теги, unescape, нормализовать пробелы."""
    text = _TAG_RE.sub(" ", fragment)
    text = unescape(text)
    text = text.replace("\u200b", "").replace("\u200c", "").replace("\u200d", "")
    text = text.replace("\ufeff", "").replace("\u200e", "").replace("\u200f", "")
    return re.sub(r"\s+", " ", text).strip()


def _numeric_from_query(query: str) -> str | None:
    """Извлечь numeric_id из строки запроса (URL / `habr_N` / голый id)."""
    q = query.strip()
    if q.startswith("habr_"):
        rest = q[5:]
        return rest if rest.isdigit() else None
    if q.isdigit():
        return q
    from_url = extract_habr_numeric_id_from_text(q)
    if from_url:
        return from_url
    match = _HABR_VACANCY_PATH_RE.search(q)
    return match.group(1) if match else None


def parse_habr_vacancy_html(html: str, *, url: str = "") -> RawVacancy:
    """Страница вакансии career.habr.com → RawVacancy. Без сети.

    Primary: парсинг SSR-JSON (`<script type="application/json" data-ssr-state="true">`).
    Fallback: JSON-LD (`<script type="application/ld+json">`).
    """
    if not (html or "").strip():
        raise InvalidInput("пустой HTML вакансии Хабр", code="vacancy_parse")

    # --- SSR-JSON (primary) ---
    ssr_match = _SSR_JSON_RE.search(html)
    ssr_data: dict[str, Any] | None = None
    if ssr_match:
        try:
            ssr_data = json.loads(ssr_match.group(1))
        except json.JSONDecodeError:
            ssr_data = None

    if ssr_data and isinstance(ssr_data.get("vacancy"), dict):
        vac = ssr_data["vacancy"]
        return _build_from_ssr(vac, url=url)

    # --- JSON-LD fallback ---
    ld_match = _JSON_LD_RE.search(html)
    ld_data: dict[str, Any] | None = None
    if ld_match:
        try:
            ld_data = json.loads(ld_match.group(1))
        except json.JSONDecodeError:
            ld_data = None

    if ld_data and isinstance(ld_data, dict):
        return _build_from_json_ld(ld_data, url=url)

    raise InvalidInput(
        "не удалось разобрать страницу вакансии Хабр (нет SSR-JSON и JSON-LD)",
        code="vacancy_parse",
    )


def _build_from_ssr(vac: dict[str, Any], *, url: str = "") -> RawVacancy:
    """Сборка RawVacancy из SSR-JSON (объект `vacancy`)."""
    numeric = str(vac.get("id", ""))
    vacancy_id = _canonical_vacancy_id(numeric) if numeric else ""

    title = str(vac.get("title", "") or "").strip()
    company = str((vac.get("company") or {}).get("title", "") or "").strip()

    salary_data = vac.get("salary") or {}
    salary_text = str(salary_data.get("formatted", "") or "").strip()

    # Локация: humanCityNames, иначе shortGeo, иначе первый locations.title
    area = str(vac.get("humanCityNames", "") or "").strip()
    if not area:
        locations = vac.get("locations") or []
        if locations:
            area = str(locations[0].get("title", "") or "").strip()

    # Формат работы: remoteWork → "удалённо" / "офис"
    remote = vac.get("remoteWork")
    work_format = "удалённо" if remote is True else ""

    # Навыки
    raw_skills = vac.get("skills") or []
    skills = [str(s.get("title", "") or "").strip() for s in raw_skills if s.get("title")]
    skills = [s for s in skills if s]

    # Квалификация
    qualification = str(vac.get("qualification", "") or "").strip() or None

    # Специализации (divisions)
    divisions = vac.get("divisions") or []
    division_titles = [str(d.get("title", "") or "").strip() for d in divisions if d.get("title")]
    division_titles = [d for d in division_titles if d]

    # Дата публикации (пока не используется — `RawVacancy` не несёт published_at)
    pub_date = vac.get("publishedDate") or {}
    del pub_date  # структура данных под будущий перенос published_at в контракт

    # Описание (HTML ставим как есть)
    description_html = str(vac.get("description", "") or "").strip()
    description_text = _strip_html(description_html) if description_html else ""

    # URL вакансии
    vacancy_url = url.strip()
    if not vacancy_url and numeric:
        vacancy_url = f"https://career.habr.com/vacancies/{numeric}"

    # Сборка `text` для LLM: мета + структурированные инжекты + описание
    parts: list[str] = []
    if title:
        parts.append(title)
    if company:
        parts.append(f"Компания: {company}")
    if salary_text:
        parts.append(f"Зарплата: {salary_text}")
    if area:
        parts.append(f"Локация: {area}")
    if skills:
        parts.append(f"Навыки: {', '.join(skills)}")
    if qualification:
        parts.append(f"Квалификация: {qualification}")
    if division_titles:
        parts.append(f"Специализации: {', '.join(division_titles)}")
    if description_text:
        parts.append("")
        parts.append(description_text)
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
        source="habr",
    )


def _build_from_json_ld(data: dict[str, Any], *, url: str = "") -> RawVacancy:
    """Сборка RawVacancy из JSON-LD (fallback)."""
    title = str(data.get("title", "") or "").strip()
    description = str(data.get("description", "") or "").strip()
    description_text = _strip_html(description) if description else description

    # baseSalary
    base_salary = data.get("baseSalary") or {}
    salary_min_raw = base_salary.get("value", "")
    # JSON-LD: value может быть числом или объектом {"@type": "QuantitativeValue", "minValue": ...}
    if isinstance(salary_min_raw, dict):
        salary_min = salary_min_raw.get("minValue", "")
    else:
        salary_min = salary_min_raw
    salary_currency = base_salary.get("currency", "")
    salary_text = ""
    if salary_min:
        currency_label = {"RUB": "₽", "USD": "$", "EUR": "€"}.get(salary_currency, "")
        salary_text = f"от {salary_min} {currency_label}".strip()

    # hiringOrganization
    org = data.get("hiringOrganization") or {}
    company = str(org.get("name", "") or "").strip()

    # identifier — может быть строкой ("identifier": "42") или объектом
    # ({"identifier": {"@type": "PropertyValue", "value": "..."}})
    identifier = data.get("identifier") or {}
    if isinstance(identifier, dict):
        numeric = str(identifier.get("value", "") or "").strip()
    else:
        numeric = str(identifier or "").strip()
    vacancy_id = _canonical_vacancy_id(numeric) if numeric else ""

    # Сборка text
    parts: list[str] = []
    if title:
        parts.append(title)
    if company:
        parts.append(f"Компания: {company}")
    if salary_text:
        parts.append(f"Зарплата: {salary_text}")
    if description_text:
        parts.append("")
        parts.append(description_text)
    text = "\n".join(p for p in parts if p).strip()

    if not title and not description_text and not numeric:
        raise InvalidInput(
            "не удалось разобрать JSON-LD страницы вакансии Хабр",
            code="vacancy_parse",
        )

    vacancy_url = url.strip()
    if not vacancy_url and numeric:
        vacancy_url = f"https://career.habr.com/vacancies/{numeric}"

    return RawVacancy(
        vacancy_id=vacancy_id,
        url=vacancy_url,
        title=title,
        company=company,
        text=text,
        salary_text=salary_text,
        area="",
        work_format="",
        source="habr",
    )


class HabrVacancySource:
    """Реализация `VacancySource` для career.habr.com."""

    name = "habr"

    async def fetch(self, query: str) -> list[RawVacancy]:
        q = (query or "").strip()
        if not q:
            raise InvalidInput("пустой запрос источника habr", code="vacancy_fetch")

        numeric = _numeric_from_query(q)
        if numeric is None:
            raise InvalidInput(
                "ожидается URL/id вакансии habr (habr_{id})",
                code="vacancy_fetch",
            )

        parsed = urlparse(q)
        if parsed.scheme in ("http", "https") and "career.habr.com" in parsed.netloc:
            url = q
        else:
            url = f"https://career.habr.com/vacancies/{numeric}"

        async with httpx.AsyncClient(
            headers=DEFAULT_HEADERS,
            timeout=25.0,
            follow_redirects=True,
        ) as client:
            response = await client.get(url)
            response.raise_for_status()
            html = response.text
        return [parse_habr_vacancy_html(html, url=url)]

    def parse(self, html: str) -> RawVacancy:
        return parse_habr_vacancy_html(html)


__all__ = [
    "HabrVacancySource",
    "extract_habr_numeric_id_from_text",
    "map_habr_qualification",
    "parse_habr_vacancy_html",
]
