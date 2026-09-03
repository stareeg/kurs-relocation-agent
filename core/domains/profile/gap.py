"""Gap-анализ резюме против корпуса реальных вакансий из PG.

Детерминированная часть (regex):
1. Корпус `vacancy_text` из `jobs` → спрос по словарю `CONCEPTS` (IT-сегмент; A-02 — n-граммный
   `corpus_terms` больше не участвует, см. `compile_concepts`).
2. Сверка с markdown-резюме → missing/strong.
3. Быстрые компоненты балла: `structure`, `market_coverage`.


LLM-часть (тир extract, фоном через `score_refresh`):
4. `writing` — слабые буллеты (`weak_bullets`).
5. `role_fit` — релевантность целевой роли.

`total` = среднее доступных компонент. `GET /api/resume/gap` не ждёт LLM:
отдаёт быстрый срез + последний снимок / эвристики, refresh — BackgroundTasks.
"""

# Плотные regex-таблицы концептов держим по одной строке на концепт (читаемее как lookup),
# поэтому E501 для файла отключён осознанно (как в исходном скрипте JS-2.2).
# ruff: noqa: E501

from __future__ import annotations

import hashlib
import logging
import re
import time
from collections import OrderedDict
from typing import Literal

from pydantic import BaseModel, Field

from core.domains.profile.bullet_format import parse_bullets
from core.domains.profile.model import ResumeData
from core.domains.profile.structured_store import (
    read_resume_data_for_account,
    render_resume_markdown_for_account,
)

logger = logging.getLogger(__name__)

# Концепт → список regex-паттернов (RU+EN формы, любой матч = вакансия требует концепт).
# Группы: язык/ядро, LLM-core, RAG, LLMOps/eval, ML-classic, data, infra, lead.
CONCEPTS: dict[str, list[str]] = {
    # --- языки и ядро ---
    "Python": [r"\bpython\b", r"\bпайтон\b"],
    "SQL": [r"\bsql\b"],
    "Go/Golang": [r"\bgolang\b", r"\bна go\b", r"\bязык go\b"],
    "Java/Scala": [r"\bjava\b", r"\bscala\b", r"\bскала\b"],
    "C++": [r"\bc\+\+\b"],
    "Async Python / asyncio": [r"asyncio", r"\basync\b", r"асинхрон"],
    # --- LLM core ---
    "LLM / большие языковые модели": [r"\bllm\b", r"больши\w* язык", r"language model"],
    "Prompt engineering": [r"prompt[- ]?engineer", r"промпт[- ]?инжен", r"\bпромпт"],
    "Fine-tuning / дообучение": [
        r"fine[- ]?tun",
        r"дообуч",
        r"тюнинг модел",
        r"\bsft\b",
        r"\blora\b",
        r"\bpeft\b",
    ],
    "RAG": [r"\brag\b", r"retrieval[- ]aug"],
    "Embeddings / эмбеддинги": [r"embedding", r"эмбеддинг", r"векторн\w* представлен"],
    "Vector DB": [
        r"vector\s*(db|database|store)",
        r"векторн\w* (бд|баз)",
        r"faiss",
        r"qdrant",
        r"milvus",
        r"pgvector",
        r"chroma",
        r"weaviate",
        r"opensearch",
        r"elasticsearch",
    ],
    "Multi-agent / агенты": [r"multi[- ]?agent", r"мультиаг", r"\bагент", r"agentic"],
    "LangChain": [r"langchain"],
    "LangGraph": [r"langgraph"],
    "LlamaIndex": [r"llamaindex", r"llama[- ]index"],
    "Function calling / tool use": [
        r"function[- ]?call",
        r"tool[- ]?(use|call)",
        r"\btool calling\b",
        r"вызов\w* функц",
        r"инструмент\w* агент",
    ],
    "Reasoning / CoT": [
        r"reasoning",
        r"chain[- ]of[- ]thought",
        r"\bcot\b",
        r"\breact\b",
        r"reflexion",
        r"reasoning model",
    ],
    # --- RAG advanced ---
    "GraphRAG / Knowledge Graph": [
        r"graphrag",
        r"knowledge graph",
        r"граф\w* знаний",
        r"\bneo4j\b",
        r"граф\w* rag",
    ],
    "Hybrid / semantic search": [
        r"hybrid (search|retrieval)",
        r"semantic search",
        r"гибридн\w* поиск",
        r"семантич\w* поиск",
    ],
    "Re-ranking": [r"re[- ]?rank", r"реранк", r"cross[- ]?encoder", r"cohere rerank"],
    # --- LLMOps / eval ---
    "MLOps": [r"\bmlops\b"],
    "LLMOps / LLM observability": [
        r"\bllmops\b",
        r"llm[- ]?ops",
        r"llm observ",
        r"observability",
        r"наблюдаем",
    ],
    "Evaluation / метрики качества": [
        r"evaluation",
        r"\beval\b",
        r"\bevals\b",
        r"\bragas\b",
        r"faithfulness",
        r"groundedness",
        r"llm[- ]as[- ]a?[- ]?judge",
        r"метрик\w* качеств",
        r"оценк\w* качеств",
    ],
    "Monitoring / трейсинг": [
        r"monitoring",
        r"мониторинг",
        r"tracing",
        r"трейсинг",
        r"langsmith",
        r"langfuse",
        r"\bphoenix\b",
    ],
    "Guardrails / safety": [
        r"guardrail",
        r"prompt injection",
        r"\bpii\b",
        r"jailbreak",
        r"\bsafety\b",
        r"гайдрейл",
    ],
    # --- ML classic ---
    "ML / машинное обучение": [r"machine learning", r"машинн\w* обучен", r"\bml\b"],
    "Deep Learning / нейросети": [
        r"deep learning",
        r"глубок\w* обучен",
        r"нейросет",
        r"нейронн\w* сет",
        r"neural network",
    ],
    "PyTorch / TensorFlow": [r"pytorch", r"tensorflow", r"\bjax\b", r"\bkeras\b"],
    "Transformers / HuggingFace": [r"transformer", r"трансформер", r"hugging\s*face", r"\bbert\b"],
    "NLP": [r"\bnlp\b", r"natural language", r"обработк\w* (естественн\w* )?язык"],
    "Computer Vision": [r"computer vision", r"\bcv\b", r"компьютерн\w* зрен"],
    "Recommender / ranking": [r"recommend", r"рекомендат", r"ранжиров", r"ranking"],
    "Classic ML (boosting и пр.)": [
        r"catboost",
        r"xgboost",
        r"lightgbm",
        r"scikit",
        r"sklearn",
        r"градиентн\w* бустинг",
        r"\bбустинг\b",
    ],
    # --- data ---
    "Spark / big data": [r"\bspark\b", r"\bhadoop\b", r"\bhdfs\b", r"big data", r"больши\w* данн"],
    "Kafka / стриминг": [r"kafka", r"кафка", r"streaming", r"стриминг"],
    "Airflow / оркестрация ETL": [
        r"airflow",
        r"\bdag\b",
        r"\bdbt\b",
        r"\betl\b",
        r"оркестрац\w* пайплайн",
    ],
    "ClickHouse / Greenplum / Trino": [
        r"clickhouse",
        r"кликхаус",
        r"greenplum",
        r"гринплам",
        r"\btrino\b",
        r"presto",
    ],
    "PostgreSQL": [r"postgres", r"постгрес"],
    "Data Warehouse / витрины": [r"\bdwh\b", r"data warehouse", r"хранилищ\w* данн", r"витрин"],
    # --- infra ---
    "Docker": [r"docker", r"докер", r"контейнер"],
    "Kubernetes": [r"kubernetes", r"\bk8s\b", r"openshift", r"кубернет"],
    "CI/CD": [r"ci/?cd", r"jenkins", r"gitlab ci", r"github actions"],
    "REST API / FastAPI": [
        r"\bfastapi\b",
        r"\brest\b",
        r"\bapi\b",
        r"grpc",
        r"микросервис",
        r"microservice",
    ],
    "Cloud (AWS/GCP/Yandex)": [
        r"\baws\b",
        r"\bgcp\b",
        r"\bazure\b",
        r"yandex cloud",
        r"облач",
        r"\bs3\b",
    ],
    "vLLM / inference serving": [
        r"vllm",
        r"triton",
        r"\btgi\b",
        r"\bonnx\b",
        r"\bsglang\b",
        r"inference server",
        r"serving",
    ],
    # --- lead / soft ---
    "Team lead / управление": [
        r"team[- ]?lead",
        r"тимлид",
        r"руковод",
        r"управлен\w* команд",
        r"lead the team",
        r"возглав",
    ],
    "Mentoring / менторство": [
        r"менторст",
        r"наставнич",
        r"mentoring",
        r"развит\w* команд",
        r"1:1",
    ],
    "Архитектура систем": [r"архитектур", r"architect", r"system design", r"проектиров\w* систем"],
    "Code review": [r"code[- ]?review", r"ревью кода", r"код[- ]?ревью"],
}

# Порог «востребованного» концепта — встречается ≥10% корпуса (как в исходном скрипте).
DEMANDED_THRESHOLD = 0.10


class GapConcept(BaseModel):
    """Один концепт в отчёте: спрос по корпусу + присутствие в резюме."""

    name: str
    demand_count: int = Field(description="В скольких вакансиях корпуса встречается")
    demand_pct: float = Field(description="Доля вакансий корпуса, 0..100")
    present: bool = Field(description="Есть ли концепт в текущем резюме")


class WeakBullet(BaseModel):
    """Слабый буллет резюме — по вердикту LLM или regex-fallback.

    `index` — позиция места работы в `ResumeData.experience` (для инлайн-подсветки в форме);
    `None` для буллетов из «Обо мне». `reason` — заполнен только на LLM-пути.
    """

    section: str = Field(description="'experience' | 'about'")
    ref: str = Field(description="Человекочитаемая привязка: «Компания — Должность» / «Обо мне»")
    index: int | None = Field(
        default=None, description="Индекс в ResumeData.experience, если раздел опыта"
    )
    text: str
    reason: str | None = Field(
        default=None, description="Что именно слабое (LLM-путь); None на regex-fallback"
    )


ApplyAction = Literal["replace_bullet", "strengthen_block", "add_skill", "patch_about"]
FixSection = Literal["experience", "about", "skills", "title"]


class ScoreFixItem(BaseModel):
    """Пункт structured-аудита: что сняло баллы и готовая правка."""

    axis: Literal["writing", "role_fit"]
    points_lost: int = Field(ge=1, le=20, description="Баллы снятые с шкалы 0–100 за этот пункт")
    label: str = Field(description="Куда: компания / Обо мне / Навыки — без дубля должности")
    current: str = Field(description="Цитата текущей формулировки")
    suggested: str = Field(description="Конкретная замена — готовый текст")
    why: str = Field(max_length=160)
    section: FixSection = "experience"
    experience_index: int | None = None
    apply_action: ApplyAction = "replace_bullet"


class ResumeScoreMeta(BaseModel):
    """Метаданные балла: устарел ли снимок, идёт ли фоновый refresh."""

    stale: bool = False
    refreshing: bool = False
    scored_at: str | None = Field(default=None, description="ISO-время последнего полного снимка")
    writing_ready: bool = False
    role_fit_ready: bool = False
    resume_hash: str = ""
    corpus_fp: str = ""


class StructureCriterion(BaseModel):
    """Один именованный критерий каркаса (чек-лист structure)."""

    id: str = Field(description="Стабильный ключ критерия")
    label: str = Field(description="Человекочитаемая формулировка «что проверить»")
    ok: bool = Field(description="True = критерий выполнен")


class ResumeScoreDetails(BaseModel):
    """Конкретные пункты «что доработать» по шкалам.

    `structure` — именованный чек-лист (контакты/даты/секции).
    `market_missing` — топ недостающих концептов (имена); writing → `weak_bullets`,
    role_fit → `role_fit_notes` на самом breakdown.
    """

    structure: list[StructureCriterion] = Field(default_factory=list)
    market_missing: list[str] = Field(
        default_factory=list, description="Топ востребованных концептов, которых нет в резюме"
    )


class ResumeScoreBreakdown(BaseModel):
    """Балл резюме 0-100 из доступных компонент, equal mean.

    `structure` / `market_coverage` — детерминизм (быстрый путь).
    `writing` / `role_fit` — extract-LLM в фоне, на cold path — эвристики.
    `market_coverage is None` — нет словаря/корпуса, в `total` не входит.
    """

    total: int = Field(description="Среднее доступных компонент, 0-100")
    structure: int = Field(description="Каркас: контакты, опыт с датами, должность и секции")
    market_coverage: int | None = Field(
        description="Покрытие рынка: blend спроса корпуса и топ-вакансий; None = нет данных"
    )
    writing: int = Field(description="Формулировки: доля сильных буллетов")
    role_fit: int = Field(description="Релевантность целевой роли")
    weak_bullets: list[WeakBullet] = Field(
        default_factory=list, description="Слабые буллеты (для подсветки / спойлера формулировок)"
    )
    role_fit_notes: list[str] = Field(
        default_factory=list, description="Короткие заметки role_fit для спойлера (legacy)"
    )
    score_fixes: list[ScoreFixItem] = Field(
        default_factory=list,
        description="Structured аудит: пункты writing/role_fit с points_lost и suggested",
    )
    details: ResumeScoreDetails = Field(
        default_factory=ResumeScoreDetails,
        description="Чек-лист каркаса и топ недостающих концептов",
    )


class ResumeGapReport(BaseModel):
    """Срез «резюме vs рынок» для вкладки «Резюме»."""

    available: bool = Field(
        description="Корпус вакансий доступен и непуст (PG поднят). False → спрос не посчитан"
    )
    corpus_size: int = Field(default=0, description="Сколько вакансий с текстом в корпусе")
    tags_count: int | None = Field(
        default=None, description="Число ATS-тегов в блоке «Навыки» резюме (None = не распарсили)"
    )
    concepts_total: int = 0
    concepts_covered: int = Field(default=0, description="Сколько концептов покрыто резюме")
    demanded_total: int = Field(default=0, description="Концептов со спросом ≥10% корпуса")
    demanded_covered: int = Field(default=0, description="Из востребованных — покрыто резюме")
    missing: list[GapConcept] = Field(
        default_factory=list, description="Востребовано, но в резюме НЕТ (спрос убыв.)"
    )
    strong: list[GapConcept] = Field(
        default_factory=list, description="Есть в резюме И востребовано ≥10% (спрос убыв.)"
    )
    score: ResumeScoreBreakdown | None = Field(
        default=None, description="Балл резюме 0-100 (4 компоненты). None = структурного резюме нет"
    )
    score_meta: ResumeScoreMeta | None = Field(
        default=None, description="stale/refreshing — для фонового обновления плашки"
    )
    score_blocked: bool = Field(
        default=False,
        description="True — левая панель критериев не заполнена, балл не считаем",
    )
    score_block_hints: list[str] = Field(
        default_factory=list,
        description="Что заполнить в левой панели, чтобы включить балл резюме",
    )


# Стемы активных глаголов действия (RU, разные времена/формы/лица) — матчим ГДЕ УГОДНО в строке,
# не только первым словом: реальные буллеты этого резюме топик-first («Time-to-market … упал»,
# «Reviewer по схеме … ловит»), а не «Managed X» с глаголом в начале, как в англоязычных гайдах.
ACTION_VERB_STEMS = (
    "разработа",
    "разрабат",
    "внедр",
    "стро",
    "спроектир",
    "проектир",
    "оптимизир",
    "сократ",
    "срез",
    "увелич",
    "повыс",
    "сниз",
    "ускор",
    "автоматизир",
    "реализ",
    "запуст",
    "созда",
    "написа",
    "писа",
    "настро",
    "подключ",
    "интегр",
    "мигр",
    "рефактор",
    "обуч",
    "тестир",
    "исправ",
    "замен",
    "вывел",
    "вывод",
    "дёрн",
    "дерн",
    "тащ",
    "управля",
    "вёл",
    "вел",
    "веду",
    "руковод",
    "координир",
    "отвеча",
    "занима",
    "поддержив",
    "сопровожда",
    "улучш",
    "расшир",
    "масштабир",
    "перевё",
    "перенес",
    "перенёс",
    "закры",
    "лов",
    "переписыва",
    "переписал",
    "теря",
    "уход",
    "высвобод",
    "роут",
    "деплои",
    "деплой",
    "инжект",
    "снял",
    "убрал",
    "убира",
    "поднял",
    "поднима",
    "прошёл",
    "прошел",
    "внёс",
    "внес",
    "сформир",
    "довел",
    "довёл",
    "приорит",
    "закрыва",
    "закрыл",
    "готов",
)
_ACTION_VERB_RE = re.compile("|".join(ACTION_VERB_STEMS), re.IGNORECASE)

# Буллет — явный маркер в начале строки (см. `bullet_format.parse_bullets`).


def _allows_builtin_concepts(market_segment: str) -> bool:
    """Зашитый IT-словарь CONCEPTS — только при пустом сегменте или наличии «IT» в выбранных."""
    seg = (market_segment or "").strip()
    if not seg:
        return True
    # Мульти-выбор: «IT» может быть одной из нескольких отраслей (через запятую).
    parts = [p.strip() for p in seg.split(",")]
    return any(p.casefold().startswith("it") for p in parts if p)


def _resolve_market_segment(market_segment: str | None) -> str:
    if market_segment is not None:
        return market_segment.strip()
    try:
        from core.domains.profile.profile import load_search_profile

        return (load_search_profile().market_segment or "").strip()
    except Exception:  # noqa: BLE001 — gap не должен падать из-за профиля
        return ""


def compile_concepts(
    corpus_texts: list[str] | None = None,
    *,
    market_segment: str | None = None,
) -> dict[str, re.Pattern[str]]:
    """Словарь концептов для gap: извлечённые требования (пока нет) → CONCEPTS (только IT) → пусто.

    `corpus_texts` зарезервирован под S-02 (`vacancy_skill_requirements`) — до его готовности
    аргумент не используется: document-frequency n-граммы (`corpus_terms.extract_corpus_terms`)
    сюда больше не подмешиваются (`docs/problems.md` 2026-07-28) — они путали HR-обвязку
    («локация», «5/2») с навыками и вытесняли курируемый `CONCEPTS` на любом непустом корпусе.
    """
    segment = _resolve_market_segment(market_segment)
    if _allows_builtin_concepts(segment):
        return {name: re.compile("|".join(pats), re.IGNORECASE) for name, pats in CONCEPTS.items()}
    return {}


def count_tags(resume_text: str) -> int | None:
    """Число тегов в блоке «Навыки» резюме (строка `**Навыки:** a, b, c`). Не нашли → None."""
    match = re.search(r"(?im)^\s*[-*\s]*\**\s*Навыки:?\**\s*(.+)$", resume_text)
    if not match:
        return None
    tags = [t.strip() for t in match.group(1).split(",") if t.strip()]
    return len(tags) or None


def compute_report(
    corpus_texts: list[str],
    resume_text: str,
    *,
    market_segment: str | None = None,
    patterns: dict[str, re.Pattern[str]] | None = None,
) -> ResumeGapReport:
    """Чистый расчёт отчёта по корпусу и тексту резюме (без I/O)."""
    patterns = patterns or compile_concepts(corpus_texts, market_segment=market_segment)
    tags = count_tags(resume_text)
    in_resume = {name: bool(pat.search(resume_text)) for name, pat in patterns.items()}
    concepts_covered = sum(1 for v in in_resume.values() if v)

    n = len(corpus_texts)
    if n == 0:
        # Корпус недоступен: спрос не считаем, но резюме-сторона (покрытие, теги) валидна.
        return ResumeGapReport(
            available=False,
            corpus_size=0,
            tags_count=tags,
            concepts_total=len(patterns),
            concepts_covered=concepts_covered,
        )

    demand = {name: sum(1 for x in corpus_texts if pat.search(x)) for name, pat in patterns.items()}
    ranked = sorted(demand.items(), key=lambda kv: kv[1], reverse=True)

    def concept(name: str, cnt: int) -> GapConcept:
        return GapConcept(
            name=name, demand_count=cnt, demand_pct=round(100 * cnt / n, 1), present=in_resume[name]
        )

    missing = [concept(name, cnt) for name, cnt in ranked if not in_resume[name] and cnt > 0]
    strong = [
        concept(name, cnt)
        for name, cnt in ranked
        if in_resume[name] and cnt >= DEMANDED_THRESHOLD * n
    ]
    demanded_total = sum(1 for _, cnt in ranked if cnt >= DEMANDED_THRESHOLD * n)

    return ResumeGapReport(
        available=True,
        corpus_size=n,
        tags_count=tags,
        concepts_total=len(patterns),
        concepts_covered=concepts_covered,
        demanded_total=demanded_total,
        demanded_covered=len(strong),
        missing=missing,
        strong=strong,
    )


def _bullets(text: str) -> list[str]:
    """Строки-буллеты внутри блока текста (description опыта / «Обо мне»)."""
    return parse_bullets(text)


def _is_weak_bullet(line: str) -> bool:
    """Нет ни цифры/метрики, ни узнаваемого глагола действия — общая формулировка без содержания."""
    has_number = bool(re.search(r"\d", line))
    has_verb = bool(_ACTION_VERB_RE.search(line))
    return not has_number and not has_verb


def _all_bullet_records(data: ResumeData) -> list[tuple[str, str, int | None, str]]:
    """Все буллеты резюме (section, ref, index, text) — не только «слабые» по regex.

    Вход для LLM-классификатора: LLM должен увидеть каждый буллет сам, иначе унаследует
    слепые зоны regex (пропустит слабый буллет со случайной цифрой, ложно пометит сильный без неё).
    """
    out: list[tuple[str, str, int | None, str]] = []
    for i, exp in enumerate(data.experience):
        ref = " — ".join(p for p in (exp.company, exp.position) if p) or "Опыт работы"
        for line in _bullets(exp.description):
            out.append(("experience", ref, i, line))
    for line in _bullets(data.about):
        out.append(("about", "Обо мне", None, line))
    return out


def find_weak_bullets(data: ResumeData) -> list[WeakBullet]:
    """Regex-fallback: буллеты без цифры и без явного действия. Используется, когда LLM-путь
    (`find_weak_bullets_llm`) недоступен/упал — сам по себе больше не основной путь."""
    return [
        WeakBullet(section=section, ref=ref, index=index, text=text)
        for section, ref, index, text in _all_bullet_records(data)
        if _is_weak_bullet(text)
    ]


async def find_weak_bullets_llm(data: ResumeData) -> list[WeakBullet]:
    """LLM-first слабые буллеты: один батч-вызов на все буллеты резюме, regex — fallback.

    Эталон формы — `core/scoring/funnel_status_llm.py`: LLM первым, детерминированный путь —
    страховка при сбое/отсутствии ключа, не наоборот.
    """
    records = _all_bullet_records(data)
    if not records:
        return []

    from core.domains.profile.weak_bullets_llm import resolve_weak_bullets_llm

    try:
        resolved = await resolve_weak_bullets_llm(records, resume=data)
    except Exception as exc:  # noqa: BLE001 — сбой LLM не должен ронять вкладку «Резюме»
        logger.warning("weak_bullets: LLM-классификация упала, откат на regex: %s", exc)
        resolved = None

    if resolved is not None:
        return resolved

    return [
        WeakBullet(section=section, ref=ref, index=index, text=text)
        for section, ref, index, text in records
        if _is_weak_bullet(text)
    ]


def resume_text_hash(resume_text: str) -> str:
    return hashlib.sha256(resume_text.encode("utf-8")).hexdigest()


def corpus_fingerprint(corpus_size: int, top_jobs_texts: list[str]) -> str:
    """Короткий отпечаток корпуса/топа — инвалидация кэша при новых скорингах."""
    h = hashlib.sha256()
    h.update(str(corpus_size).encode("utf-8"))
    for txt in top_jobs_texts:
        h.update(hashlib.sha256(txt.encode("utf-8")).digest())
    return h.hexdigest()[:16]


def _structure_criteria(_resume_text: str, data: ResumeData) -> list[StructureCriterion]:
    """Именованный чек-лист каркаса — источник спойлера FR2-47.

    Зарплата и markdown-шум убраны: вилка живёт в левой панели скоринга, а резюме
    заполняется формой, а не сырым markdown (таблицы/картинки туда больше не попадают).
    """
    if data.experience:
        dates_ok = all(e.start and (e.end or e.current) for e in data.experience)
    else:
        dates_ok = False
    raw: list[tuple[str, str, bool]] = [
        ("full_name", "ФИО заполнено", bool(data.personal.full_name)),
        ("contacts", "Телефон или email", bool(data.contacts.phone or data.contacts.email)),
        ("title", "Желаемая должность", bool(data.position.title)),
        ("experience", "Есть блок опыта", bool(data.experience)),
        ("dates", "У всех мест опыта есть даты", dates_ok),
        ("education", "Образование указано", bool(data.education or data.education_level)),
        ("skills", "Не меньше 5 ключевых навыков", len(data.key_skills) >= 5),
        ("about", "«Обо мне» не короче 50 символов", len(data.about.strip()) >= 50),
    ]
    return [StructureCriterion(id=i, label=label, ok=ok) for i, label, ok in raw]


def _score_structure(resume_text: str, data: ResumeData) -> int:
    """Каркас: контакты, опыт с датами, должность и секции."""
    checks = _structure_criteria(resume_text, data)
    return round(100 * sum(1 for c in checks if c.ok) / len(checks))


def _role_fit_fallback_notes(
    data: ResumeData, report: ResumeGapReport, *, resume_text: str = ""
) -> list[str]:
    """Детерминированные подсказки role_fit, когда LLM-заметок ещё нет."""
    from core.domains.profile.score_criteria import criteria_alignment_tips

    tips: list[str] = []
    if not (data.position.title or "").strip():
        tips.append("Укажите желаемую должность под целевую роль")
    tags = len([s for s in data.key_skills if s.strip()]) or (report.tags_count or 0)
    if tags < 15:
        tips.append(f"В навыках {tags} из лимита 30 - доберите сильные под роль")
    if report.available and report.missing:
        names = ", ".join(c.name for c in report.missing[:4])
        tips.append(f"В тексте мало следов рынка: {names}")
    elif not report.available:
        tips.append("Оцените несколько вакансий - тогда релевантность роли станет точнее")
    niches = data.search_criteria.niches if data.search_criteria else []
    if not niches:
        tips.append("Задайте ниши поиска в критериях - роль станет конкретнее")
    if resume_text:
        for tip in criteria_alignment_tips(data, resume_text):
            if tip not in tips:
                tips.append(tip)
    return tips[:4]


def _score_demanded_coverage(report: ResumeGapReport) -> int | None:
    """Доля востребованных концептов в резюме. Нет корпуса → None (не подставляем 100)."""
    if not report.available:
        return None
    if report.demanded_total > 0:
        return round(100 * report.demanded_covered / report.demanded_total)
    if report.concepts_total <= 0:
        return 0
    return round(100 * report.concepts_covered / report.concepts_total)


def _score_top_jobs_match(
    resume_text: str, top_jobs_texts: list[str], patterns: dict[str, re.Pattern[str]]
) -> int | None:
    """Средняя доля совпадения концептов с топ-N вакансиями. Нет топа → None."""
    if not top_jobs_texts:
        return None
    in_resume = {name: bool(pat.search(resume_text)) for name, pat in patterns.items()}
    scores: list[float] = []
    for txt in top_jobs_texts:
        vac_concepts = [name for name, pat in patterns.items() if pat.search(txt)]
        if not vac_concepts:
            continue
        hit = sum(1 for name in vac_concepts if in_resume[name])
        scores.append(hit / len(vac_concepts))
    if not scores:
        return 0
    return round(100 * sum(scores) / len(scores))


def _score_market_coverage(
    report: ResumeGapReport,
    resume_text: str,
    top_jobs_texts: list[str],
    patterns: dict[str, re.Pattern[str]] | None = None,
    *,
    corpus_texts: list[str] | None = None,
    market_segment: str | None = None,
) -> int | None:
    """Blend спроса корпуса и топ-вакансий. Нет словаря / cold start → None, не 0."""
    patterns = patterns or compile_concepts(corpus_texts, market_segment=market_segment)
    # Пустой словарь (не-IT без корпуса) — честный «нет данных», не ноль.
    if not patterns:
        return None
    parts = [
        p
        for p in (
            _score_demanded_coverage(report),
            _score_top_jobs_match(resume_text, top_jobs_texts, patterns),
        )
        if p is not None
    ]
    if not parts:
        return None
    return round(sum(parts) / len(parts))


def _score_writing(weak: list[WeakBullet], total_bullets: int) -> int:
    """Доля сильных буллетов. Нет буллетов → 0."""
    if total_bullets == 0:
        return 0
    return round(100 * (1 - len(weak) / total_bullets))


def _score_role_fit_fallback(
    data: ResumeData, report: ResumeGapReport, *, resume_text: str = ""
) -> int:
    """Эвристика без LLM: навыки + demanded; смешивается с criteria_alignment (15%)."""
    from core.domains.profile.score_criteria import blend_role_fit, score_criteria_alignment

    tags = len([s for s in data.key_skills if s.strip()]) or (report.tags_count or 0)
    if tags <= 0:
        skills_density = 0
    elif tags >= 30:
        skills_density = 100
    else:
        skills_density = round(100 * tags / 30)
    demanded = _score_demanded_coverage(report)
    primary = skills_density if demanded is None else round(0.5 * skills_density + 0.5 * demanded)
    if not resume_text.strip():
        from core.domains.profile.model import to_markdown

        resume_text = to_markdown(data)
    criteria = score_criteria_alignment(data, resume_text)
    return blend_role_fit(primary, criteria)


def count_bullets(data: ResumeData) -> int:
    return len(_bullets(data.about)) + sum(len(_bullets(e.description)) for e in data.experience)


def _with_snapshot_audit(
    score: ResumeScoreBreakdown,
    data: ResumeData,
    last: object | None,
) -> ResumeScoreBreakdown:
    """Подмешать persisted LLM-fixes из PG-снимка, если hash совпал."""
    if last is None:
        return score
    from core.domains.profile.resume_score import ResumeScoreSnapshot, audit_fixes_from_snapshot
    from core.domains.profile.score_audit import role_fit_notes_from_fixes, weak_bullets_from_fixes

    if not isinstance(last, ResumeScoreSnapshot):
        return score
    fixes = audit_fixes_from_snapshot(last)
    if not fixes:
        return score
    return score.model_copy(
        update={
            "score_fixes": fixes,
            "weak_bullets": weak_bullets_from_fixes(fixes, data),
            "role_fit_notes": role_fit_notes_from_fixes(fixes),
            "writing": last.writing,
            "role_fit": last.role_fit,
        }
    )


def reconcile_fast_writing(
    score: ResumeScoreBreakdown,
    data: ResumeData,
    weak: list[WeakBullet],
) -> ResumeScoreBreakdown:
    """Пересчитать writing/total по текущим буллетам на быстром GET-пути.

    Снимок LLM хранит только число writing — при правке текста без refresh список
    weak_bullets и шкала «Формулировки» расходились; total брал устаревший writing.
    """
    total_bullets = count_bullets(data)
    writing_v = _score_writing(weak, total_bullets)
    available = [score.structure, writing_v, score.role_fit]
    if score.market_coverage is not None:
        available.append(score.market_coverage)
    return score.model_copy(
        update={
            "writing": writing_v,
            "weak_bullets": weak,
            "total": round(sum(available) / len(available)),
        }
    )


def assemble_score(
    data: ResumeData,
    resume_text: str,
    report: ResumeGapReport,
    top_jobs_texts: list[str] | None = None,
    *,
    weak: list[WeakBullet] | None = None,
    writing: int | None = None,
    role_fit: int | None = None,
    role_fit_notes: list[str] | None = None,
    score_fixes: list[ScoreFixItem] | None = None,
    patterns: dict[str, re.Pattern[str]] | None = None,
    corpus_texts: list[str] | None = None,
    market_segment: str | None = None,
) -> ResumeScoreBreakdown:
    """Собрать 4-компонентный балл. LLM-поля можно передать готовыми или посчитать эвристикой."""
    if weak is None:
        weak = find_weak_bullets(data)
    total_bullets = count_bullets(data)
    structure_checks = _structure_criteria(resume_text, data)
    structure = round(100 * sum(1 for c in structure_checks if c.ok) / len(structure_checks))
    market = _score_market_coverage(
        report,
        resume_text,
        top_jobs_texts or [],
        patterns,
        corpus_texts=corpus_texts,
        market_segment=market_segment,
    )
    writing_v = writing if writing is not None else _score_writing(weak, total_bullets)
    role_v = (
        role_fit
        if role_fit is not None
        else _score_role_fit_fallback(data, report, resume_text=resume_text)
    )
    notes_raw = [n.strip() for n in (role_fit_notes or []) if n and n.strip()]
    from core.domains.profile.score_tips import format_role_fit_note

    notes = [n for n in (format_role_fit_note(x) for x in notes_raw) if n]
    if not notes:
        notes = [
            n
            for n in (format_role_fit_note(x) for x in _role_fit_fallback_notes(data, report, resume_text=resume_text))
            if n
        ]
    market_missing = [c.name for c in report.missing[:8]]
    available = [structure, writing_v, role_v]
    if market is not None:
        available.append(market)
    return ResumeScoreBreakdown(
        total=round(sum(available) / len(available)),
        structure=structure,
        market_coverage=market,
        writing=writing_v,
        role_fit=role_v,
        weak_bullets=weak,
        role_fit_notes=notes,
        score_fixes=list(score_fixes or []),
        details=ResumeScoreDetails(structure=structure_checks, market_missing=market_missing),
    )


# Совместимость со старым именем (тесты / импорты).
compute_score = assemble_score

# Кэш полного балла: ключ = resume_hash + corpus_fp (корпус тоже инвалидирует).
# Bounded LRU+TTL: ключ растёт с числом аккаунтов и версий резюме/корпуса, а значение тяжёлое
# (весь разбор резюме). Без вытеснения друзья владельца выедут RAM на Selectel — см. план
# «In-Memory Cache Leak». TTL = 7 дней (как llm_result_cache), лимит 256 записей — с запасом
# над числом аккаунтов × активных версий резюме.
_SCORE_CACHE_TTL_S = 7 * 24 * 3600
_SCORE_CACHE_MAX = 256
_score_cache: OrderedDict[str, tuple[ResumeScoreBreakdown, float]] = OrderedDict()
_refresh_inflight: set[str] = set()


def score_cache_key(resume_hash: str, corpus_fp: str) -> str:
    return f"{resume_hash}:{corpus_fp}"


def get_cached_score(resume_hash: str, corpus_fp: str) -> ResumeScoreBreakdown | None:
    key = score_cache_key(resume_hash, corpus_fp)
    item = _score_cache.get(key)
    if item is None:
        return None
    score, expires_mono = item
    if time.monotonic() >= expires_mono:
        _score_cache.pop(key, None)
        return None
    _score_cache.move_to_end(key)
    return score


def put_cached_score(resume_hash: str, corpus_fp: str, score: ResumeScoreBreakdown) -> None:
    key = score_cache_key(resume_hash, corpus_fp)
    _score_cache[key] = (score, time.monotonic() + _SCORE_CACHE_TTL_S)
    _score_cache.move_to_end(key)
    while len(_score_cache) > _SCORE_CACHE_MAX:
        _score_cache.popitem(last=False)


def clear_score_cache() -> None:
    """Сброс кэша балла — при обновлении резюме/корпуса (см. `_refresh_caches_and_publish`)."""
    _score_cache.clear()


def is_refresh_inflight(cache_key: str) -> bool:
    return cache_key in _refresh_inflight


def mark_refresh_inflight(cache_key: str, active: bool) -> None:
    if active:
        _refresh_inflight.add(cache_key)
    else:
        _refresh_inflight.discard(cache_key)


async def compute_score_async(
    data: ResumeData,
    resume_text: str,
    report: ResumeGapReport,
    top_jobs_texts: list[str] | None = None,
    *,
    account_id: int,
    corpus_texts: list[str] | None = None,
    market_segment: str | None = None,
    patterns: dict[str, re.Pattern[str]] | None = None,
) -> ResumeScoreBreakdown:
    """Полный балл с LLM-аудитом (writing + role_fit + fixes). Для фонового refresh."""
    r_hash = resume_text_hash(resume_text)
    c_fp = corpus_fingerprint(report.corpus_size, top_jobs_texts or [])
    cached = get_cached_score(r_hash, c_fp)
    if cached is not None:
        return cached

    from core.domains.profile.score_audit import (
        resolve_score_audit_llm,
        role_fit_notes_from_fixes,
        weak_bullets_from_fixes,
    )
    from core.domains.profile.score_criteria import blend_role_fit, score_criteria_alignment

    audit = await resolve_score_audit_llm(data, report, account_id=account_id)
    if audit is not None:
        writing_score, role_primary, fixes = audit
        criteria = score_criteria_alignment(data, resume_text)
        role_score = blend_role_fit(role_primary, criteria)
        weak = weak_bullets_from_fixes(fixes, data)
        notes = role_fit_notes_from_fixes(fixes)
        breakdown = assemble_score(
            data,
            resume_text,
            report,
            top_jobs_texts,
            weak=weak,
            writing=writing_score,
            role_fit=role_score,
            role_fit_notes=notes,
            score_fixes=fixes,
            patterns=patterns,
            corpus_texts=corpus_texts,
            market_segment=market_segment,
        )
        put_cached_score(r_hash, c_fp, breakdown)
        return breakdown

    import asyncio

    from core.domains.profile.role_fit_llm import resolve_role_fit_llm

    weak_task = asyncio.create_task(find_weak_bullets_llm(data))
    role_task = asyncio.create_task(
        resolve_role_fit_llm(data, report, top_jobs_texts or [], account_id=account_id)
    )
    weak, role_result = await asyncio.gather(weak_task, role_task)

    role_score: int | None
    role_notes: list[str]
    if role_result is not None:
        role_primary, role_notes = role_result
        criteria = score_criteria_alignment(data, resume_text)
        role_score = blend_role_fit(role_primary, criteria)
    else:
        role_score = None
        role_notes = []

    breakdown = assemble_score(
        data,
        resume_text,
        report,
        top_jobs_texts,
        weak=weak,
        writing=_score_writing(weak, count_bullets(data)),
        role_fit=role_score,
        role_fit_notes=role_notes,
        patterns=patterns,
        corpus_texts=corpus_texts,
        market_segment=market_segment,
    )
    put_cached_score(r_hash, c_fp, breakdown)
    return breakdown


async def load_corpus(*, account_id: int, db: object | None = None) -> list[tuple[str, str, str]]:
    """Корпус (title, company, vacancy_text) аккаунта запроса из PG. Без skipped — калибровка,
    не отказы. `account_id` обязателен (plans/multitenancy_gaps_2026_08_06.md §3.1 п.3) —
    раньше запрос не фильтровал по аккаунту вовсе и кормил расчёт скора резюме корпусом
    вакансий всех аккаунтов."""
    if db is None:
        from core.platform.db.pool import get_pool

        db = get_pool()
    from core.domains.opportunities.jobs import SQL_JOB_NOT_SKIPPED

    rows = await db.fetch(  # type: ignore[attr-defined]
        "select coalesce(title,'') t, coalesce(company,'') c, coalesce(vacancy_text,'') x "
        "from jobs where account_id = $1 and vacancy_text is not null and length(vacancy_text) > 150 "
        f"and {SQL_JOB_NOT_SKIPPED}",
        account_id,
    )
    return [(r["t"], r["c"], r["x"]) for r in rows]


async def load_top_scored_jobs(
    n: int = 10, *, account_id: int, db: object | None = None
) -> list[str]:
    """Топ-N vacancy_text аккаунта запроса по overall_score — для market_coverage / role_fit /
    ATS (без skipped)."""
    if n <= 0:
        return []
    if db is None:
        from core.platform.db.pool import get_pool

        db = get_pool()
    from core.domains.opportunities.jobs import SQL_JOB_NOT_SKIPPED

    rows = await db.fetch(  # type: ignore[attr-defined]
        "select coalesce(vacancy_text,'') x from jobs "
        "where account_id = $1 and vacancy_text is not null and overall_score is not null "
        f"and {SQL_JOB_NOT_SKIPPED} "
        "order by overall_score desc limit $2",
        account_id,
        n,
    )
    return [r["x"] for r in rows if r["x"]]


async def load_top_scored_summaries(
    n: int = 5, *, account_id: int, db: object | None = None
) -> list[tuple[str, str]]:
    """Топ-N (title, company) аккаунта запроса для промпта role_fit (без skipped)."""
    if n <= 0:
        return []
    if db is None:
        from core.platform.db.pool import get_pool

        db = get_pool()
    from core.domains.opportunities.jobs import SQL_JOB_NOT_SKIPPED

    rows = await db.fetch(  # type: ignore[attr-defined]
        "select coalesce(title,'') t, coalesce(company,'') c from jobs "
        "where account_id = $1 and vacancy_text is not null and overall_score is not null "
        f"and {SQL_JOB_NOT_SKIPPED} "
        "order by overall_score desc limit $2",
        account_id,
        n,
    )
    return [(r["t"], r["c"]) for r in rows if r["t"] or r["c"]]


async def build_gap_report(
    resume_text: str | None = None, *, account_id: int, db: object | None = None
) -> ResumeGapReport:
    """Быстрый отчёт: regex-gap + structure/market сейчас; writing/role_fit из кэша/снимка/эвристик.

    LLM не ждём — `score_meta.stale=True` сигналит роутеру запустить BackgroundTasks refresh.
    `account_id` — аккаунт запроса (plans/multitenancy_gaps_2026_08_06.md §3.1): резюме,
    корпус вакансий и снимок скора резолвятся строго для него, не для владельца-по-умолчанию.
    """
    from core.domains.profile.profile import derive_candidate_profile
    from core.domains.profile.score_criteria import left_panel_gaps, left_panel_hints

    if resume_text is None:
        resume_text = await render_resume_markdown_for_account(account_id, db=db)  # type: ignore[arg-type]
    data = await read_resume_data_for_account(account_id, db=db)  # type: ignore[arg-type]
    profile = derive_candidate_profile(data)

    try:
        corpus = await load_corpus(account_id=account_id, db=db)
    except Exception as exc:  # noqa: BLE001
        logger.debug("gap: корпус из Postgres недоступен: %s", exc)
        corpus = []

    try:
        top_jobs_texts = await load_top_scored_jobs(10, account_id=account_id, db=db)
    except Exception as exc:  # noqa: BLE001
        logger.debug("gap: топ-N вакансий недоступен: %s", exc)
        top_jobs_texts = []

    corpus_texts = [x for _, _, x in corpus]
    patterns = compile_concepts(corpus_texts, market_segment=profile.market_segment)
    report = compute_report(corpus_texts, resume_text, patterns=patterns)

    panel_gaps = left_panel_gaps(data)
    if panel_gaps:
        from core.platform.observability import event

        report.score_blocked = True
        report.score_block_hints = left_panel_hints(data)
        event(
            logger,
            "СОБЫТИЕ",
            "балл резюме заблокирован: gaps=%s",
            panel_gaps,
            account_id=account_id,
            gaps=panel_gaps,
            hints=report.score_block_hints,
        )
        return report

    r_hash = resume_text_hash(resume_text)
    c_fp = corpus_fingerprint(report.corpus_size, top_jobs_texts)
    cache_key = score_cache_key(r_hash, c_fp)

    cached = get_cached_score(r_hash, c_fp)
    if cached is not None:
        if cached.score_fixes:
            report.score = cached
        else:
            weak_display = find_weak_bullets(data)
            report.score = reconcile_fast_writing(cached, data, weak_display)
        report.score_meta = ResumeScoreMeta(
            stale=False,
            refreshing=is_refresh_inflight(cache_key),
            writing_ready=True,
            role_fit_ready=True,
            resume_hash=r_hash,
            corpus_fp=c_fp,
        )
        return report

    last = None
    try:
        from core.domains.profile.resume_score import load_score_at

        last = await load_score_at(account_id=account_id, db=db)  # type: ignore[arg-type]
    except Exception as exc:  # noqa: BLE001
        logger.debug("gap: последний снимок скора недоступен: %s", exc)

    fresh_match = (
        last is not None
        and (last.resume_hash or "") == r_hash
        and (last.corpus_fp or "") == c_fp
        and last.writing_ready
        and last.role_fit_ready
    )
    # Regex-weak на быстром пути; writing пересчитываем из них, role_fit — из снимка/LLM.
    weak_display = find_weak_bullets(data)

    if fresh_match and last is not None:
        score = assemble_score(
            data,
            resume_text,
            report,
            top_jobs_texts,
            weak=weak_display,
            writing=last.writing,
            role_fit=last.role_fit,
            patterns=patterns,
            corpus_texts=corpus_texts,
        )
        score = _with_snapshot_audit(score, data, last)
        if not score.score_fixes:
            score = reconcile_fast_writing(score, data, weak_display)
        available = [score.structure, score.writing, score.role_fit]
        if score.market_coverage is not None:
            available.append(score.market_coverage)
        score = score.model_copy(update={"total": round(sum(available) / len(available))})
        put_cached_score(r_hash, c_fp, score)
        report.score = score
        report.score_meta = ResumeScoreMeta(
            stale=False,
            refreshing=False,
            scored_at=last.created_at.isoformat() if last.created_at else None,
            writing_ready=True,
            role_fit_ready=True,
            resume_hash=r_hash,
            corpus_fp=c_fp,
        )
        return report

    # Stale / cold: быстрые компоненты + role_fit из снимка или эвристик; writing — из буллетов.
    role_fit: int | None = last.role_fit if last is not None else None
    score = assemble_score(
        data,
        resume_text,
        report,
        top_jobs_texts,
        weak=weak_display,
        writing=None,
        role_fit=role_fit,
        patterns=patterns,
        corpus_texts=corpus_texts,
    )
    score = reconcile_fast_writing(score, data, weak_display)
    if last is not None and (last.resume_hash or "") == r_hash:
        score = _with_snapshot_audit(score, data, last)
        if score.score_fixes:
            available = [score.structure, score.writing, score.role_fit]
            if score.market_coverage is not None:
                available.append(score.market_coverage)
            score = score.model_copy(update={"total": round(sum(available) / len(available))})
    report.score = score
    report.score_meta = ResumeScoreMeta(
        stale=True,
        refreshing=is_refresh_inflight(cache_key),
        scored_at=last.created_at.isoformat() if last and last.created_at else None,
        writing_ready=bool(last and last.writing_ready and last.resume_hash == r_hash),
        role_fit_ready=bool(last and last.role_fit_ready and last.resume_hash == r_hash),
        resume_hash=r_hash,
        corpus_fp=c_fp,
    )
    return report
