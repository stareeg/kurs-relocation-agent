"""Канонизация названий компаний.

Детерминированная нормализация (оргформы, кавычки, регистр, хвосты, алиасы) — основной путь;
для backfill её достаточно. Если после неё имя всё ещё «мусорное» (длиннее 40
символов или похоже на слоган) — одноразовый вызов extract-тира вытаскивает бренд.
"""

from __future__ import annotations

import logging
import re
from functools import lru_cache
from pathlib import Path

from pydantic import BaseModel, Field

from core.config import get_settings
from core.domains.opportunities.llm import COMPANY_NORMALIZE
from core.kernel import ports
from core.kernel.errors import LlmError
from core.platform.observability import event

logger = logging.getLogger(__name__)

__all__ = [
    "COMPANY_ALIASES",
    "needs_brand_extract",
    "normalize_company",
    "normalize_company_deterministic",
]

# Ключ — lower/folded после strip оргформ; значение — канон для UI/матчинга.
# Короткий расширяемый словарь; совпадение по полному ключу (не подстрока).
COMPANY_ALIASES: dict[str, str] = {
    # Сбер
    "sber": "Сбербанк",
    "sberbank": "Сбербанк",
    "сбер": "Сбербанк",
    "сбербанк": "Сбербанк",
    "сбертех": "Сбербанк",
    "sbertech": "Сбербанк",
    # Яндекс
    "yandex": "Яндекс",
    "яндекс": "Яндекс",
    # VK
    "vk": "VK",
    "вк": "VK",
    "вконтакте": "VK",
    "mail.ru": "VK",
    "mailru": "VK",
    # Т-Банк
    "т-банк": "Т-Банк",
    "тбанк": "Т-Банк",
    "тинькофф": "Т-Банк",
    "тинькофф банк": "Т-Банк",
    "tinkoff": "Т-Банк",
    "t-bank": "Т-Банк",
    "tbank": "Т-Банк",
    # Прочие частые
    "авито": "Авито",
    "avito": "Авито",
    "мтс": "МТС",
    "mts": "МТС",
    "mws": "МТС",
    "ozon": "Ozon",
    "озон": "Ozon",
    "wildberries": "Wildberries",
    "вайлдберриз": "Wildberries",
    "wb": "Wildberries",
    "втб": "ВТБ",
    "vtb": "ВТБ",
    "альфа-банк": "Альфа-Банк",
    "альфа банк": "Альфа-Банк",
    "alfabank": "Альфа-Банк",
    "alfa-bank": "Альфа-Банк",
    "газпромбанк": "Газпромбанк",
    "gazprombank": "Газпромбанк",
    "kaspersky": "Kaspersky",
    "касперский": "Kaspersky",
    "лаборатория касперского": "Kaspersky",
}

_MAX_BRAND_LEN = 40

# Полные формы и аббревиатуры оргформ — только как отдельные токены (границы слова).
_ORG_TOKEN = (
    r"(?:публичное\s+акционерное\s+общество|открытое\s+акционерное\s+общество|"
    r"закрытое\s+акционерное\s+общество|общество\s+с\s+ограниченной\s+ответственностью|"
    r"пао|оао|ооо|зао|ао|ип|ltd\.?|llc\.?|inc\.?|gmbh|corp\.?|plc\.?|co\.?)"
)
_ORG_PREFIX = re.compile(rf"^{_ORG_TOKEN}\s+", re.IGNORECASE)
_ORG_SUFFIX = re.compile(rf"[\s,]+{_ORG_TOKEN}\s*$", re.IGNORECASE)

_QUOTES = re.compile(r"[«»\"'`„“”‚‘’]")

# Хвосты вроде «, группа компаний» / «холдинг» в конце строки.
_TAIL = re.compile(
    r"[\s,]+(?:"
    r"группа\s+компаний|групп[аы]\s+компани\w*|"
    r"group\s+of\s+companies|holding(?:\s+group)?|холдинг|"
    r"и\s+партн[её]ры|and\s+partners|"
    r"llc|ltd|inc"
    r")\s*$",
    re.IGNORECASE,
)

# Слоган / маркетинговый мусор в «названии» работодателя с hh.
_SLOGAN = re.compile(
    r"(?:"
    r"лидер\s+рынка|инновационн|мы\s+(?:ищем|созда|дела)|"
    r"best\s+place|join\s+us|hiring|dream\s+job|"
    r"вакансия|карьер[аы]|работа\s+мечт|"
    r"меняем\s+мир|делаем\s+мир|созда[её]м\s+будущ"
    r")",
    re.IGNORECASE,
)

# Разделители, после которых часто идёт слоган/описание, а не бренд.
_SLOGAN_SPLIT = re.compile(r"\s+[—–|:]\s+|\s+-\s+")


class _BrandExtract(BaseModel):
    brand: str = Field(default="", description="Короткое каноническое имя бренда")


def _fold_key(name: str) -> str:
    """Ключ для словаря алиасов: lower + ё→е + схлопнутые пробелы."""
    s = name.casefold().replace("ё", "е")
    return re.sub(r"\s+", " ", s).strip()


def _strip_org_forms(name: str) -> str:
    s = name.strip()
    # Несколько проходов: «ООО ПАО …» и «Name, ООО» встречаются редко, но дёшево.
    for _ in range(3):
        nxt = _ORG_PREFIX.sub("", s)
        nxt = _ORG_SUFFIX.sub("", nxt)
        nxt = nxt.strip(" ,.-")
        if nxt == s:
            break
        s = nxt
    return s


def _strip_tails(name: str) -> str:
    s = name.strip()
    for _ in range(2):
        nxt = _TAIL.sub("", s).strip(" ,.-")
        if nxt == s:
            break
        s = nxt
    return s


def _display_case(name: str) -> str:
    """Регистр неизвестных брендов: слова с заглавной; LATIN ALLCAPS ≤4 без изменений."""
    parts: list[str] = []
    for word in name.split():
        if word.isupper() and 2 <= len(word) <= 4 and word.isascii():
            parts.append(word)
        elif word.isupper() and word.isascii() and len(word) > 4:
            parts.append(word.capitalize())
        else:
            parts.append(word[:1].upper() + word[1:].lower() if word else word)
    return " ".join(parts)


def _clean_raw(raw: str) -> str:
    s = _QUOTES.sub("", (raw or "").strip())
    s = re.sub(r"\s+", " ", s)
    s = _strip_org_forms(s)
    s = _strip_tails(s)
    s = _strip_org_forms(s)  # хвост мог оставить «ООО» с краю
    return re.sub(r"\s+", " ", s).strip(" ,.-")


def normalize_company_deterministic(raw: str | None) -> str:
    """Детерминированная канонизация без LLM. Пустой вход → пустая строка."""
    if raw is None:
        return ""
    cleaned = _clean_raw(raw)
    if not cleaned:
        return ""
    alias = COMPANY_ALIASES.get(_fold_key(cleaned))
    if alias:
        return alias
    # Иногда бренд + хвост описания через тире: берём левую часть, если она короче и есть алиас.
    split = _SLOGAN_SPLIT.split(cleaned, maxsplit=1)
    if len(split) == 2 and split[0].strip():
        left = split[0].strip()
        left_alias = COMPANY_ALIASES.get(_fold_key(left))
        if left_alias:
            return left_alias
        if len(left) <= _MAX_BRAND_LEN and not _SLOGAN.search(left):
            cleaned = left
    return _display_case(cleaned)


def needs_brand_extract(canonical: str) -> bool:
    """True, если детерминированный результат всё ещё похож на мусор/слоган."""
    name = (canonical or "").strip()
    if not name:
        return False
    if len(name) > _MAX_BRAND_LEN:
        return True
    if _SLOGAN.search(name):
        return True
    # Точка в длинной строке — почти никогда бренд (слоган/описание).
    return name.count(".") >= 1 and len(name) > 20


@lru_cache(maxsize=1)
def _load_prompt() -> str:
    path = Path(COMPANY_NORMALIZE)
    if not path.is_file():
        raise FileNotFoundError(f"Промпт канонизации компаний не найден: {path}")
    return path.read_text(encoding="utf-8").strip()


async def _extract_brand_llm(raw: str) -> str | None:
    """Одноразовый extract-тир: выделить бренд. None при сбое/пустом ответе."""
    if not get_settings().openrouter_api_key:
        return None
    try:
        system = _load_prompt()
        result = await ports.llm().structured(
            "company_normalize",
            system=system,
            user=raw.strip(),
            schema=_BrandExtract,
            temperature=0.0,
        )
    except (LlmError, FileNotFoundError, OSError) as exc:
        # Мягкая деградация: детерминированный путь уже дал имя — предупреждение, не отказ.
        event(
            logger,
            "ОШИБКА",
            "канонизация компании: LLM fallback сбой",
            level=logging.WARNING,
            error=str(exc),
        )
        return None
    brand = (result.brand or "").strip()
    return brand or None


async def normalize_company(raw: str | None, *, allow_llm: bool = True) -> str:
    """Полная канонизация: детерминизм, при мусоре — extract-тир (если allow_llm)."""
    det = normalize_company_deterministic(raw)
    if not det:
        return ""
    if not allow_llm or not needs_brand_extract(det):
        return det
    extracted = await _extract_brand_llm(raw or det)
    if not extracted:
        return det
    # Повторный детерминизм: срежет оргформы/алиасы, которые LLM мог вернуть сырьём.
    refined = normalize_company_deterministic(extracted)
    return refined or det
