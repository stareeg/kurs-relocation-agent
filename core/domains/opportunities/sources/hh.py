"""Источник вакансий hh.ru: парсинг HTML без сети + карточка через официальный api.hh.ru.

К hh.ru (HTML выдачи/вакансии) сервер не ходит: живой discovery и скоринг страницы — в
расширении. Единственный сетевой путь — `GET https://api.hh.ru/vacancies/{id}` по явному
действию (ссылка в бота), с честным User-Agent, без ретраев и без подделки Chrome.
"""

from __future__ import annotations

import json
import logging
import os
import re
from html import unescape
from pathlib import Path
from typing import Any
from urllib.parse import parse_qs, urlencode, urlparse, urlunparse

import httpx

from core.domains.opportunities.discovered import DiscoveredVacancy
from core.kernel.errors import InvalidInput, Unprocessable
from core.kernel.vacancy import RawVacancy
from core.platform.observability import event

logger = logging.getLogger(__name__)

HH_SEARCH_PATH = "/search/vacancy"
VACANCIES_MARKERS = (',"vacancies":', '"vacancies":')
VACANCY_ID_RE = re.compile(r"/vacancy/(\d+)")
DESCRIPTION_RE = re.compile(
    r'data-qa=["\']vacancy-description["\'][^>]*>(.*?)</div>',
    re.DOTALL | re.IGNORECASE,
)
TAG_RE = re.compile(r"<[^>]+>")
# data-qa и обычный h1 — два альтернативных захвата; берём первый непустой.
TITLE_RE = re.compile(
    r'(?:data-qa=["\']vacancy-title["\'][^>]*>(.*?)</h1>|<h1[^>]*>(.*?)</h1>)',
    re.DOTALL | re.IGNORECASE,
)
COMPANY_RE = re.compile(
    r'data-qa=["\']vacancy-company-name["\'][^>]*>(.*?)</(?:a|span|div)>',
    re.DOTALL | re.IGNORECASE,
)

HH_API_BASE = "https://api.hh.ru"
HH_SERP_DISABLED_CODE = "hh_serp_fetch_disabled"
HH_API_DENIED_CODE = "hh_api_denied"


def hh_api_user_agent() -> str:
    """Честный UA для api.hh.ru: имя продукта, не Chrome, без URL сайта и без ротации."""
    override = os.environ.get("HH_API_USER_AGENT", "").strip()
    if override:
        return override
    version = "1.0"
    manifest = Path(__file__).resolve().parents[4] / "extension" / "manifest.json"
    try:
        data = json.loads(manifest.read_text(encoding="utf-8"))
        version = str(data.get("version") or version)
    except (OSError, json.JSONDecodeError, TypeError, AttributeError):
        pass
    return f"CareerCopilot/{version}"


def _hh_api_headers() -> dict[str, str]:
    ua = hh_api_user_agent()
    return {"User-Agent": ua, "HH-User-Agent": ua, "Accept": "application/json"}


class HhSearchParseError(ValueError):
    pass


def normalize_search_url(url: str) -> str:
    parsed = urlparse(url.strip())
    if "hh.ru" not in parsed.netloc and "hh." not in parsed.netloc:
        raise HhSearchParseError("URL должен быть с домена hh.ru")
    if HH_SEARCH_PATH not in parsed.path:
        raise HhSearchParseError(f"Ожидается путь {HH_SEARCH_PATH}")
    return urlunparse(parsed)


def search_url_for_page(search_url: str, page: int) -> str:
    """page: 0-based для HH (параметр page=0,1,2...)."""
    parsed = urlparse(normalize_search_url(search_url))
    qs = parse_qs(parsed.query, keep_blank_values=True)
    qs["page"] = [str(page)]
    new_query = urlencode(qs, doseq=True)
    return urlunparse(parsed._replace(query=new_query))


def _strip_html(fragment: str) -> str:
    text = TAG_RE.sub(" ", fragment)
    return re.sub(r"\s+", " ", unescape(text)).strip()


def _compensation_text(comp: dict[str, Any]) -> str:
    if not comp:
        return ""
    parts = []
    for key in ("from", "to"):
        val = comp.get(key)
        if val is not None:
            parts.append(str(val))
    currency = comp.get("currencyCode") or comp.get("currency")
    if parts:
        s = " – ".join(parts) if len(parts) == 2 else parts[0]
        if currency:
            s = f"{s} {currency}"
        return s
    return comp.get("text") or comp.get("@summary") or ""


# Новая таксономия формата работы hh (поле `workFormats`) → русский. Точнее legacy
# `@workSchedule`, где формат и график смешаны (fullDay/remote/shift…).
_WORK_FORMAT_RU = {
    "REMOTE": "удалённо",
    "HYBRID": "гибрид",
    "ON_SITE": "на месте работодателя",
    "FIELD_WORK": "разъездная работа",
}


def _work_format_text(raw: dict[str, Any]) -> str:
    """Формат работы (удалённо/гибрид/офис) из `workFormats`, с фолбэком на legacy `@workSchedule`.

    В SERP-JSON приходит как `workFormats: [{"workFormatsElement": ["REMOTE", "HYBRID"]}]`.
    Если поля нет (старая выдача) и `@workSchedule == "remote"` - считаем удалёнкой.
    """
    formats = raw.get("workFormats") or raw.get("work_format") or []
    codes: list[str] = []
    for entry in formats:
        if isinstance(entry, dict):
            elems = entry.get("workFormatsElement") or entry.get("id") or entry.get("name") or []
            if isinstance(elems, str):
                elems = [elems]
            codes.extend(str(e) for e in elems)
        elif isinstance(entry, str):
            codes.append(entry)

    seen: list[str] = []
    for code in codes:
        cu = code.strip().upper()
        if cu and cu not in seen:
            seen.append(cu)

    fmt = ", ".join(_WORK_FORMAT_RU.get(code, code.lower()) for code in seen)
    if fmt:
        return fmt

    legacy = str(raw.get("@workSchedule") or raw.get("workSchedule") or "").strip().lower()
    return "удалённо" if legacy == "remote" else ""


def _map_vacancy_dict(raw: dict[str, Any]) -> DiscoveredVacancy | None:
    vid = raw.get("vacancyId") or raw.get("id")
    if vid is None:
        return None
    vacancy_id = str(vid)
    links = raw.get("links") or {}
    url = links.get("desktop") or links.get("mobile") or f"https://hh.ru/vacancy/{vacancy_id}"

    company = raw.get("company") or {}
    company_name = company.get("name") or company.get("@title") or company.get("title") or ""
    employer_id = company.get("id")
    if employer_id is not None:
        employer_id = str(employer_id)

    area = raw.get("area") or {}
    area_name = area.get("name") or area.get("@title") or ""

    schedule = raw.get("@workSchedule") or raw.get("workSchedule") or ""
    work_format = _work_format_text(raw)
    letter = raw.get("@responseLetterRequired")
    if letter is None:
        letter = raw.get("responseLetterRequired")

    return DiscoveredVacancy(
        vacancy_id=vacancy_id,
        url=url,
        title=(raw.get("name") or raw.get("title") or "").strip(),
        company=str(company_name).strip(),
        salary_text=_compensation_text(raw.get("compensation") or {}),
        area=str(area_name).strip(),
        work_format=work_format,
        work_schedule=str(schedule).strip(),
        total_responses=raw.get("totalResponsesCount"),
        letter_required=bool(letter) if letter is not None else None,
        employer_id=employer_id,
        source="search_batch",
    )


def extract_vacancies_from_html(html: str) -> list[DiscoveredVacancy]:
    """Embedded JSON (предпочтительно) или regex по /vacancy/ID.

    Этап 6 §6.1 (plans/scoring_precision_2026_08_17.md): живая проверка hh.ru 2026-08-18 показала
    два наложившихся дефекта в актуальной вёрстке SERP, из-за которых этот путь всегда молча
    проваливался в regex-фолбэк (только vacancy_id, без total_responses/salary/work_format/
    letter_required):
    1. Блок теперь HTML-entity-encoded (`&#34;` вместо `"` — лежит в атрибуте, не в сыром
       `<script>` JSON), маркер на закодированном виде не матчился вовсе.
    2. У части карточек `mapData` (координаты офиса — JSON-строка-в-строке) продублирован
       экранирующий бэкслеш перед КАЖДОЙ внутренней кавычкой (`\\\\&#34;` вместо `\\&#34;`) —
       по правилам JSON это законно обрывает строковое значение раньше времени и валит разбор
       всего массива на первом же элементе. `mapData` не используется — сворачиваем двойной
       бэкслеш перед закодированной кавычкой обратно в одинарный ДО unescape/JSON-парсинга.
    `unescape` — no-op на уже плоском HTML, поэтому легаси-случай (`<script>` с сырым JSON,
    без двойного экранирования) не ломается ни одним из двух шагов.
    """
    decoded = unescape(html.replace("\\\\&#34;", "\\&#34;"))
    marker = next((m for m in VACANCIES_MARKERS if m in decoded), None)
    if marker:
        try:
            chunk = decoded.split(marker, 1)[1]
            decoder = json.JSONDecoder()
            raw_list, _ = decoder.raw_decode(chunk)
            if isinstance(raw_list, list):
                out: list[DiscoveredVacancy] = []
                for item in raw_list:
                    if isinstance(item, dict):
                        mapped = _map_vacancy_dict(item)
                        if mapped:
                            out.append(mapped)
                if out:
                    return out
        except (json.JSONDecodeError, ValueError) as exc:
            logger.warning("Не удалось распарсить embedded vacancies: %s", exc)

    seen: set[str] = set()
    fallback: list[DiscoveredVacancy] = []
    for match in VACANCY_ID_RE.finditer(html):
        vid = match.group(1)
        if vid in seen:
            continue
        seen.add(vid)
        fallback.append(
            DiscoveredVacancy(
                vacancy_id=vid,
                url=f"https://hh.ru/vacancy/{vid}",
                title="",
                source="search_batch_fallback",
            )
        )
    return fallback


def _serp_fetch_disabled() -> Unprocessable:
    return Unprocessable(
        "серверный обход выдачи hh выключен — откройте поиск в браузере с расширением",
        code=HH_SERP_DISABLED_CODE,
    )


async def discover_from_search_url(
    search_url: str,
    *,
    max_pages: int = 1,
    limit: int | None = None,
    fetch_full_description: bool = False,
    page_delay_sec: float = 1.0,
) -> tuple[list[DiscoveredVacancy], int]:
    """Серверный обход SERP выключен (Шаг 5). Живой discovery — в расширении.

    Сигнатура сохранена: тесты подменяют функцию. Сети нет.
    """
    del search_url, max_pages, limit, fetch_full_description, page_delay_sec
    raise _serp_fetch_disabled()


def _api_salary_text(salary: dict[str, Any] | None) -> str:
    if not salary:
        return ""
    mapped = {
        "from": salary.get("from"),
        "to": salary.get("to"),
        "currencyCode": salary.get("currency") or salary.get("currencyCode"),
    }
    text = _compensation_text(mapped)
    if not text:
        return str(salary.get("text") or "").strip()
    if salary.get("gross") is True:
        return f"{text} до вычета налогов"
    if salary.get("gross") is False:
        return f"{text} на руки"
    return text


def parse_hh_vacancy_api(payload: dict[str, Any]) -> RawVacancy:
    """JSON `GET /vacancies/{id}` → RawVacancy. Без сети."""
    if not isinstance(payload, dict) or not payload:
        raise InvalidInput("пустой ответ api.hh.ru", code="vacancy_parse")

    vid = str(payload.get("id") or "").strip()
    if not vid:
        raise InvalidInput("в ответе api.hh.ru нет id вакансии", code="vacancy_parse")

    title = str(payload.get("name") or "").strip()
    employer_raw = payload.get("employer")
    employer: dict[str, Any] = employer_raw if isinstance(employer_raw, dict) else {}
    company = str(employer.get("name") or "").strip()
    area_raw = payload.get("area")
    area: dict[str, Any] = area_raw if isinstance(area_raw, dict) else {}
    area_name = str(area.get("name") or "").strip()
    work_format = _work_format_text(payload)
    if not work_format:
        schedule_raw = payload.get("schedule")
        schedule: dict[str, Any] = schedule_raw if isinstance(schedule_raw, dict) else {}
        sched_id = str(schedule.get("id") or "").strip().lower()
        if sched_id == "remote":
            work_format = "удалённо"
        elif schedule.get("name"):
            work_format = str(schedule["name"]).strip()
    salary_text = _api_salary_text(
        payload.get("salary") if isinstance(payload.get("salary"), dict) else None
    )
    description = _strip_html(str(payload.get("description") or ""))
    skills_raw = payload.get("key_skills") or []
    skills = [
        str(item.get("name")).strip()
        for item in skills_raw
        if isinstance(item, dict) and item.get("name")
    ] or None
    url = str(payload.get("alternate_url") or f"https://hh.ru/vacancy/{vid}").strip()
    parts = [
        title,
        f"Компания: {company}" if company else "",
        f"Зарплата: {salary_text}" if salary_text else "",
        f"Локация: {area_name}" if area_name else "",
        f"Формат работы: {work_format}" if work_format else "",
        description,
    ]
    text = "\n".join(p for p in parts if p).strip()
    if not title and not description:
        raise InvalidInput("не удалось разобрать ответ api.hh.ru", code="vacancy_parse")
    return RawVacancy(
        vacancy_id=vid,
        url=url,
        title=title,
        company=company,
        text=text,
        salary_text=salary_text,
        area=area_name,
        work_format=work_format,
        source="hh",
        skills=skills,
    )


async def fetch_hh_vacancy_api(
    vacancy_id: str,
    *,
    timeout: float = 15.0,
    transport: httpx.BaseTransport | None = None,
) -> RawVacancy:
    """Одна вакансия с api.hh.ru. Без ретраев: 403/404/429 → честный отказ, не HTML-скрейпинг."""
    vid = (vacancy_id or "").strip()
    if not vid or not vid.isdigit():
        raise InvalidInput("ожидается числовой id вакансии hh", code="vacancy_fetch")
    url = f"{HH_API_BASE}/vacancies/{vid}"
    kwargs: dict[str, Any] = {
        "headers": _hh_api_headers(),
        "timeout": timeout,
        "follow_redirects": True,
    }
    if transport is not None:
        kwargs["transport"] = transport
    try:
        async with httpx.AsyncClient(**kwargs) as client:
            response = await client.get(url)
    except httpx.HTTPError as exc:
        event(
            logger,
            "РАСШИРЕНИЕ",
            "api.hh.ru недоступен: %s",
            type(exc).__name__,
            level=logging.WARNING,
            event="hh_api_denied",
            vacancy_id=vid,
            reason="network",
        )
        raise Unprocessable(
            "hh не отдал вакансию — откройте ссылку в браузере с расширением",
            code=HH_API_DENIED_CODE,
        ) from exc

    if response.status_code != 200:
        event(
            logger,
            "РАСШИРЕНИЕ",
            "api.hh.ru отказал: HTTP %s",
            response.status_code,
            level=logging.WARNING,
            event="hh_api_denied",
            vacancy_id=vid,
            status=response.status_code,
        )
        raise Unprocessable(
            "hh не отдал вакансию — откройте ссылку в браузере с расширением",
            code=HH_API_DENIED_CODE,
        )
    try:
        payload = response.json()
    except ValueError as exc:
        raise InvalidInput("ответ api.hh.ru не JSON", code="vacancy_parse") from exc
    if not isinstance(payload, dict):
        raise InvalidInput("ответ api.hh.ru не объект", code="vacancy_parse")
    return parse_hh_vacancy_api(payload)


def _vacancy_id_from_query(query: str) -> str | None:
    q = query.strip()
    if q.isdigit():
        return q
    match = VACANCY_ID_RE.search(q)
    return match.group(1) if match else None


def parse_hh_vacancy_html(html: str, *, url: str = "") -> RawVacancy:
    """Страница вакансии hh → RawVacancy. Без сети."""
    if not (html or "").strip():
        raise InvalidInput("пустой HTML вакансии hh", code="vacancy_parse")

    vid = _vacancy_id_from_query(url) or None
    if vid is None:
        match = VACANCY_ID_RE.search(html)
        vid = match.group(1) if match else ""

    title_m = TITLE_RE.search(html)
    title = ""
    if title_m:
        title = _strip_html(next((g for g in title_m.groups() if g), "") or "")

    company_m = COMPANY_RE.search(html)
    company = _strip_html(company_m.group(1)) if company_m else ""

    desc_m = DESCRIPTION_RE.search(html)
    description = _strip_html(desc_m.group(1)) if desc_m else ""

    if not title and not description and not vid:
        raise InvalidInput("не удалось разобрать страницу вакансии hh", code="vacancy_parse")

    vacancy_url = url.strip() or (f"https://hh.ru/vacancy/{vid}" if vid else "")
    parts = [
        title,
        f"Компания: {company}" if company else "",
        description,
    ]
    text = "\n".join(p for p in parts if p).strip()

    return RawVacancy(
        vacancy_id=vid or "",
        url=vacancy_url,
        title=title,
        company=company,
        text=text,
        source="hh",
    )


class HhVacancySource:
    """Реализация `VacancySource` для hh.ru."""

    name = "hh"

    async def fetch(self, query: str) -> list[RawVacancy]:
        q = (query or "").strip()
        if not q:
            raise InvalidInput("пустой запрос источника hh", code="vacancy_fetch")

        try:
            normalize_search_url(q)
        except HhSearchParseError:
            pass
        else:
            raise _serp_fetch_disabled()

        vid = _vacancy_id_from_query(q)
        if vid is None:
            raise InvalidInput(
                "ожидается id или URL вакансии hh.ru",
                code="vacancy_fetch",
            )
        return [await fetch_hh_vacancy_api(vid)]

    def parse(self, html: str) -> RawVacancy:
        return parse_hh_vacancy_html(html)


__all__ = [
    "HH_API_DENIED_CODE",
    "HH_SERP_DISABLED_CODE",
    "HhSearchParseError",
    "HhVacancySource",
    "discover_from_search_url",
    "extract_vacancies_from_html",
    "fetch_hh_vacancy_api",
    "hh_api_user_agent",
    "parse_hh_vacancy_api",
    "parse_hh_vacancy_html",
]
