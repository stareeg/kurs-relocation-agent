"""Профили этапов под РФ-бигтех 2026.

Статическое доменное знание: как типовые компании РФ проводят этапы собеса. Профиль
детектится по названию компании из вакансии (`match_company_profile`) и влияет на состав
подготовки - формат этапа уезжает в промпт генерации вопросов (`core.domains.preparation.interview.prep`), а
доп. пункты под формат компании - в чеклист «за 3 часа до». Переиспользуемо ботом и вебом.

Стиль текста - рубленые строки, без длинных тире и эмодзи (CLAUDE.md, стиль владельца).
Формулировки намеренно про устойчивые черты процесса (алгоритмы / system design / on-prem /
highload / fintech), а не про сиюминутные детали - чтобы знание не протухало. Поэтому
«обычно/как правило»: точный состав секций у компании меняется, рамка - нет.

Ключи этапов - те же, что `core.domains.preparation.models.PrepStage`: этапы воронки
(screening / tech / final / hr_final) и форматы технички вкладки «Технички»
(theory / system_design / live_coding / business_case / other). Нет ключа под формат →
профиль всё равно применяется (общая инструкция + summary), просто без спец-заметки.

Общая рамка компании (highload / fintech / on-prem / алгоритмы) - про компанию, специальность-
агностична, оставлена как есть. А вот что компания спрашивает ПО СПЕЦИАЛИЗАЦИИ кандидата раньше
было зашито буквально как "ML/LLM" (изначально писалось под Lead LLM Engineer) - вместо
этого в текстах плейсхолдер `{{SPECIALIZATION}}`, подставляемый в рантайме (`match_company_profile`)
нишей ИЗ РЕЗЮМЕ кандидата (`core.domains.profile.identity.candidate_specialization_line`), так же, как
`{{CANDIDATE_IDENTITY}}` подставляется в статических промптах.
"""

from __future__ import annotations

import re

from pydantic import BaseModel, Field

from core.domains.opportunities.prompt import load_candidate_specialization

__all__ = [
    "CompanyProfile",
    "COMPANY_PROFILES",
    "SPECIALIZATION_TOKEN",
    "match_company_profile",
    "resolve_company_profile",
]

# Плейсхолдер в summary/stage_notes/stage_tips профилей - см. докстринг модуля.
SPECIALIZATION_TOKEN = "{{SPECIALIZATION}}"


class CompanyProfile(BaseModel):
    """Профиль формата собеса конкретной компании РФ-бигтеха."""

    key: str
    name: str
    # Токены для детекта по названию компании. Короткие (<=3 симв.) матчатся как целое слово,
    # длинные - как префикс слова (чтобы «сбер» ловил «сбербанк»/«сбертех»).
    aliases: tuple[str, ...] = ()
    summary: str = ""
    # Как компания обычно проводит этот этап. Уходит в промпт генерации вопросов.
    stage_notes: dict[str, str] = Field(default_factory=dict)
    # Доп. пункты чеклиста «за 3 часа до» под формат компании (по этапам).
    stage_tips: dict[str, list[str]] = Field(default_factory=dict)


COMPANY_PROFILES: tuple[CompanyProfile, ...] = (
    CompanyProfile(
        key="yandex",
        name="Яндекс",
        aliases=("яндекс", "yandex"),
        summary=(
            "Высокая инженерная планка. Почти всегда отдельная алгоритмическая секция в Контесте, "
            "секция по специализации ({{SPECIALIZATION}}), system design и финал с руководителем. "
            "Грейд калибруют по сумме секций."
        ),
        stage_notes={
            "screening": (
                "HR прощупывает мотивацию, грейд и ожидания по деньгам. Иногда сразу лёгкая "
                "алгоритмическая задача или вопрос на оценку сложности."
            ),
            "tech": (
                "Две алгоритмические задачи в Я.Контесте, ждут оптимальную сложность, чистый код "
                "и разбор edge-кейсов вслух. Плюс секция по специализации - {{SPECIALIZATION}} "
                "в проде, метрики, эффект."
            ),
            "theory": (
                "Секция по специализации проверяет фундамент - теория {{SPECIALIZATION}}, "
                "метрики, почему так. Могут спросить и теорию алгоритмов с оценкой сложности."
            ),
            "system_design": (
                "System design по их рамке под {{SPECIALIZATION}} - сбор требований, данные, "
                "метрики (оффлайн и онлайн), инфраструктура под нагрузку, мониторинг качества "
                "и деградаций."
            ),
            "live_coding": (
                "Две алгоритмические задачи в Я.Контесте, ждут оптимальную сложность, чистый код "
                "и разбор edge-кейсов вслух."
            ),
            "business_case": (
                "Прикладной кейс под их продукты - предложи решение по {{SPECIALIZATION}}, "
                "продуктовые метрики, оценку эффекта и нагрузки."
            ),
            "final": (
                "Секция с руководителем и калибровка грейда. Про ownership, влияние на продукт, "
                "как принимаешь технические решения."
            ),
            "hr_final": (
                "Оффер и грейд по их сетке, вилка под грейд, формат и условия. Торг по грейду "
                "реален, если секции прошёл сильно."
            ),
        },
        stage_tips={
            "screening": ["Будь готов к лёгкой алгозадаче прямо на скрининге"],
            "tech": [
                "Прорешай 2-3 алгозадачи medium на время в онлайн-редакторе",
                "Проговаривай сложность по времени и памяти вслух, разбирай edge-кейсы",
            ],
            "theory": ["Освежи фундамент и метрики {{SPECIALIZATION}}"],
            "system_design": [
                "Держи рамку Яндекса - требования, оффлайн и онлайн метрики, инфра инференса, "
                "мониторинг дрейфа",
            ],
            "live_coding": [
                "Прорешай 2-3 алгозадачи medium на время в онлайн-редакторе",
                "Проговаривай сложность по времени и памяти вслух, разбирай edge-кейсы",
            ],
            "business_case": ["Свяжи решение с продуктовыми метриками и оценкой нагрузки"],
        },
    ),
    CompanyProfile(
        key="sber",
        name="Сбер",
        aliases=("сбер", "sber"),
        summary=(
            "Упор не на чистые алгоритмы, а на прикладную {{SPECIALIZATION}}, архитектуру и прод. "
            "Свой стек, часто on-prem (OpenShift), требования по безопасности данных и "
            "импортозамещению. Экосистема GigaChat."
        ),
        stage_notes={
            "screening": (
                "HR про мотивацию, грейд, деньги и готовность к их стеку. Часто on-prem "
                "инфраструктура и свои платформы."
            ),
            "tech": (
                "Прикладные вопросы по {{SPECIALIZATION}} и эксплуатации в проде - как доводил "
                "решения до продакшена, мониторил и откатывал. Алгоритмов меньше, прикладухи больше."
            ),
            "theory": (
                "Прикладная теория {{SPECIALIZATION}} и безопасность данных. "
                "Чистых алгоритмов меньше, упор на «как работает и почему так»."
            ),
            "system_design": (
                "Проектирование системы под их масштаб и ограничения - on-prem, "
                "безопасность данных, отказоустойчивость, импортозамещение стека."
            ),
            "live_coding": (
                "Лайвкодинг прикладной - реализовать кусок пайплайна или бизнес-логики по "
                "{{SPECIALIZATION}}, чистых алгоритмов меньше, чем прикладухи."
            ),
            "business_case": (
                "Кейс под их масштаб - on-prem и импортозамещение как ограничения, экосистема "
                "GigaChat, эффект решения для банка."
            ),
            "final": (
                "Руководитель направления про команду, лидерство, влияние и зону ответственности."
            ),
            "hr_final": (
                "Оффер по их грейдовой сетке, ДМС, формат (часто гибрид, полную удалёнку "
                "обсуждать отдельно), сроки выхода."
            ),
        },
        stage_tips={
            "tech": [
                "Подготовь прод-кейсы по {{SPECIALIZATION}} под on-prem ограничения",
                "Освежи их экосистему - GigaChat, своя платформа, OpenShift",
            ],
            "theory": ["Освежи прикладную теорию {{SPECIALIZATION}} и безопасность данных"],
            "system_design": [
                "Закладывай on-prem, безопасность данных и импортозамещение как явные ограничения",
            ],
            "live_coding": [
                "Готовь практический код под пайплайн по {{SPECIALIZATION}}, не чистые алгоритмы"
            ],
            "business_case": ["Закладывай on-prem и импортозамещение, свяжи с эффектом для банка"],
        },
    ),
    CompanyProfile(
        key="tbank",
        name="Т-Банк",
        aliases=("т-банк", "тбанк", "тинькофф", "tinkoff", "t-bank", "tbank"),
        summary=(
            "Высокая инженерная планка, интенсивный live coding и несколько технических секций. "
            "Fintech, свой стек и highload, сильная культура разработки."
        ),
        stage_notes={
            "screening": "HR про опыт и мотивацию, иногда короткий технический скрининг.",
            "tech": (
                "Интенсивный live coding - алгоритмы и практические задачи, плюс глубокие вопросы "
                "по специализации. Ждут скорость и чистый код."
            ),
            "theory": (
                "Глубокие вопросы по специализации и фундаменту под их fintech-стек - "
                "просят объяснить как работает и почему так."
            ),
            "system_design": (
                "Дизайн сервиса под highload и fintech - надёжность, консистентность данных, "
                "отказоустойчивость, нагрузки."
            ),
            "live_coding": (
                "Интенсивный live coding - алгоритмы medium и практические задачи на время. "
                "Ждут скорость, чистый код и разбор edge-кейсов вслух."
            ),
            "business_case": (
                "Кейс под fintech - надёжность, консистентность данных, эффект решения на продукт."
            ),
            "final": "Руководитель про ownership, влияние и как тащишь задачи.",
            "hr_final": (
                "Оффер и вилка. Формат уточняй - у Т-Банка часто офис или гибрид, полную удалёнку "
                "проговаривай явно."
            ),
        },
        stage_tips={
            "tech": [
                "Разомнись на live coding - алгоритм medium плюс практическая задача на время"
            ],
            "theory": ["Освежи фундамент по специализации под их fintech-стек"],
            "system_design": ["Готовь дизайн под highload и консистентность данных fintech"],
            "live_coding": [
                "Разомнись на live coding - алгоритм medium плюс практическая задача на время",
                "Тренируй скорость и проговаривание сложности вслух",
            ],
            "business_case": ["Готовь кейс под fintech - надёжность и консистентность данных"],
            "hr_final": ["Проговори полную удалёнку явно - у Т-Банка часто офис или гибрид"],
        },
    ),
    CompanyProfile(
        key="avito",
        name="Авито",
        aliases=("авито", "avito"),
        summary=(
            "Продуктовая компания с highload. Сильная алгоритмическая секция, system design "
            "высоконагруженных сервисов, упор на impact и продуктовые метрики."
        ),
        stage_notes={
            "screening": "HR про опыт, мотивацию и ожидания.",
            "tech": (
                "Алгоритмическая секция (live coding) плюс прикладные вопросы по "
                "{{SPECIALIZATION}}. Думают про highload и производительность."
            ),
            "theory": (
                "Прикладной фундамент по {{SPECIALIZATION}} плюс продуктовое мышление - метрики, "
                "A/B, почему так."
            ),
            "system_design": (
                "Дизайн высоконагруженного сервиса под {{SPECIALIZATION}}, продуктовые метрики, "
                "A/B-эксперименты."
            ),
            "live_coding": (
                "Алгоритмическая секция live coding, держат в уме highload и производительность."
            ),
            "business_case": (
                "Продуктовый кейс - impact, A/B-эксперименты, продуктовые метрики, масштаб."
            ),
            "final": "Hiring manager про impact и продуктовое мышление.",
            "hr_final": "Оффер и вилка, формат - у Авито нормальная удалёнка и гибрид.",
        },
        stage_tips={
            "tech": [
                "Прорешай алгозадачи medium на время",
                "Подготовь пример с продуктовыми метриками и A/B",
            ],
            "theory": ["Освежи прикладную {{SPECIALIZATION}}, продуктовые метрики и A/B"],
            "system_design": ["Готовь дизайн под highload, держи в уме A/B и продуктовые метрики"],
            "live_coding": ["Прорешай алгозадачи medium на время, держи в уме производительность"],
            "business_case": ["Готовь кейс с продуктовыми метриками, A/B и масштабом"],
        },
    ),
    CompanyProfile(
        key="vk",
        name="VK",
        aliases=("вконтакте", "vk", "вк", "mail.ru"),
        summary=(
            "Highload и своя инфраструктура. Алгоритмическая секция, system design "
            "и секция по специализации."
        ),
        stage_notes={
            "screening": "HR про опыт и мотивацию.",
            "tech": (
                "Алгоритмы (live coding) плюс вопросы по специализации. Большие нагрузки "
                "и своя инфра."
            ),
            "theory": "Вопросы по специализации и фундаменту под highload и свою инфру.",
            "system_design": "Дизайн высоконагруженного сервиса, отказоустойчивость, масштабирование.",
            "live_coding": "Алгоритмическая секция live coding под большие нагрузки.",
            "business_case": "Кейс под highload-сервис - масштаб, надёжность, отказоустойчивость.",
            "final": "Руководитель про команду и ownership.",
            "hr_final": "Оффер и вилка, формат и условия.",
        },
        stage_tips={
            "tech": ["Прорешай алгозадачи medium на время"],
            "theory": ["Освежи фундамент по специализации под highload и свою инфру"],
            "system_design": ["Готовь дизайн под highload и масштабирование"],
            "live_coding": ["Прорешай алгозадачи medium на время"],
            "business_case": ["Готовь кейс под highload - масштаб и надёжность"],
        },
    ),
    CompanyProfile(
        key="mts",
        name="МТС",
        aliases=("мтс", "mts", "mws"),
        summary=(
            "Профиль компании включает MTS AI и MWS (их облако). Упор на прикладную "
            "{{SPECIALIZATION}}, эксплуатацию и облачную инфру, меньше жёстких алгоритмов."
        ),
        stage_notes={
            "screening": "HR про мотивацию, грейд и деньги.",
            "tech": (
                "Прикладные вопросы по {{SPECIALIZATION}} и эксплуатации, вопросы про их облако "
                "MWS. Алгоритмов меньше, прикладухи больше."
            ),
            "theory": (
                "Прикладная теория {{SPECIALIZATION}} и эксплуатации под их облако MWS - как "
                "работает и почему так."
            ),
            "system_design": (
                "Проектирование сервиса под {{SPECIALIZATION}} в их облаке - нагрузка, "
                "мониторинг, масштабирование."
            ),
            "live_coding": (
                "Лайвкодинг прикладной - кусок пайплайна или бизнес-логики по {{SPECIALIZATION}}, "
                "меньше чистых алгоритмов."
            ),
            "business_case": (
                "Кейс под их облако - сервис по {{SPECIALIZATION}}, нагрузка, масштаб, эффект "
                "для клиента."
            ),
            "final": "Руководитель про команду, влияние и рост.",
            "hr_final": "Оффер и вилка, формат - удалёнка и гибрид обсуждаемы.",
        },
        stage_tips={
            "tech": ["Освежи эксплуатацию и облачную инфраструктуру под их MWS"],
            "theory": ["Освежи прикладную теорию {{SPECIALIZATION}} и эксплуатации под их облако"],
            "system_design": [
                "Готовь дизайн сервиса по {{SPECIALIZATION}} в облаке - нагрузка, мониторинг, масштаб"
            ],
            "live_coding": [
                "Готовь практический код под пайплайн по {{SPECIALIZATION}}, не чистые алгоритмы"
            ],
            "business_case": ["Готовь кейс под облако MWS - нагрузка, масштаб, эффект для клиента"],
        },
    ),
    CompanyProfile(
        key="ozon",
        name="Ozon",
        aliases=("озон", "ozon"),
        summary=(
            "E-commerce и highload. Алгоритмическая секция, system design нагруженных сервисов, "
            "упор на масштаб и надёжность."
        ),
        stage_notes={
            "screening": "HR про опыт и мотивацию.",
            "tech": "Алгоритмы (live coding) плюс прикладные вопросы по {{SPECIALIZATION}} под highload.",
            "theory": "Прикладной фундамент по {{SPECIALIZATION}} под e-commerce highload.",
            "system_design": (
                "Дизайн высоконагруженного сервиса e-commerce - масштаб, надёжность, очереди."
            ),
            "live_coding": "Алгоритмическая секция live coding под e-commerce highload.",
            "business_case": "Кейс под e-commerce - масштаб, надёжность, продуктовый эффект.",
            "final": "Hiring manager про impact и ownership.",
            "hr_final": "Оффер и вилка, формат и условия.",
        },
        stage_tips={
            "tech": ["Прорешай алгозадачи medium на время"],
            "theory": ["Освежи {{SPECIALIZATION}} под e-commerce highload"],
            "system_design": [
                "Готовь дизайн под highload e-commerce - масштаб, очереди, надёжность"
            ],
            "live_coding": ["Прорешай алгозадачи medium на время"],
            "business_case": ["Готовь кейс под e-commerce - масштаб и продуктовый эффект"],
        },
    ),
    CompanyProfile(
        key="wildberries",
        name="Wildberries",
        aliases=("wildberries", "вайлдберриз", "wb", "вб"),
        summary=(
            "E-commerce и highload, быстрый рост. Алгоритмы, system design нагруженных сервисов, "
            "прикладная специализация."
        ),
        stage_notes={
            "screening": "HR про опыт и мотивацию.",
            "tech": "Алгоритмы (live coding) плюс прикладные вопросы по {{SPECIALIZATION}} под highload.",
            "theory": "Прикладной фундамент по {{SPECIALIZATION}} под e-commerce highload.",
            "system_design": (
                "Дизайн высоконагруженного сервиса e-commerce - масштаб, надёжность, очереди."
            ),
            "live_coding": "Алгоритмическая секция live coding под e-commerce highload.",
            "business_case": "Кейс под e-commerce - масштаб, надёжность, продуктовый эффект.",
            "final": "Hiring manager про impact и ownership.",
            "hr_final": "Оффер и вилка, формат и условия.",
        },
        stage_tips={
            "tech": ["Прорешай алгозадачи medium на время"],
            "theory": ["Освежи {{SPECIALIZATION}} под e-commerce highload"],
            "system_design": [
                "Готовь дизайн под highload e-commerce - масштаб, очереди, надёжность"
            ],
            "live_coding": ["Прорешай алгозадачи medium на время"],
            "business_case": ["Готовь кейс под e-commerce - масштаб и продуктовый эффект"],
        },
    ),
)


def _alias_pattern(alias: str) -> str:
    """Короткий токен (<=3) - целое слово; длинный - префикс слова (чтобы «сбер»→«сбербанк»)."""
    escaped = re.escape(alias.lower())
    return rf"\b{escaped}\b" if len(alias) <= 3 else rf"\b{escaped}"


def resolve_company_profile(profile: CompanyProfile, specialization: str) -> CompanyProfile:
    """Подставить нишу кандидата в плейсхолдер `{{SPECIALIZATION}}` профиля."""

    def _sub(text: str) -> str:
        return text.replace(SPECIALIZATION_TOKEN, specialization)

    return profile.model_copy(
        update={
            "summary": _sub(profile.summary),
            "stage_notes": {k: _sub(v) for k, v in profile.stage_notes.items()},
            "stage_tips": {k: [_sub(t) for t in v] for k, v in profile.stage_tips.items()},
        }
    )


async def match_company_profile(
    company: str | None, vacancy_text: str = "", *, account_id: int | None = None
) -> CompanyProfile | None:
    """Подобрать профиль компании по названию (надёжный сигнал) или, если пусто, началу текста.

    По тексту вакансии матчим только когда нет названия компании - чтобы упоминание «интегрируем
    Яндекс.Облако» в описании не выдавало ложный профиль. Нет совпадения → None (общая подготовка).
    Найденный профиль отдаётся уже с подставленной нишей кандидата (`resolve_company_profile`) -
    вызывающему коду (роутеры, бот) не нужно резолвить плейсхолдер самостоятельно.

    `account_id` (S-critical 2026-08-26) — специализация резюме ИМЕННО этого аккаунта, не
    легаси дефолт-аккаунтный кэш (`load_candidate_specialization()` без `data=`); `None` —
    файловый bootstrap-путь (тесты/установка без аккаунтов).
    """
    haystack = (company or "").strip().lower()
    if not haystack:
        haystack = (vacancy_text or "")[:200].strip().lower()
    if not haystack:
        return None

    for profile in COMPANY_PROFILES:
        for alias in profile.aliases:
            if re.search(_alias_pattern(alias), haystack):
                from core.domains.profile.structured_store import read_resume_data_for_account

                resume_data = await read_resume_data_for_account(account_id)
                return resolve_company_profile(
                    profile, load_candidate_specialization(data=resume_data)
                )
    return None
