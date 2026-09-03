"""Структурированная карточка вакансии для Telegram (замена пересказа текста, 2026-07-03).

Раньше `forwarded.py` пересказывал вакансию текстом — бесполезно и устарело, когда в системе уже
есть триаж-панель расширения (`extension/src/content/main.ts` `renderScore`) с чёткими
критериями. Эта карточка мирроит те же поля `ScoreResult` (скор, зарплата, удалёнка, грейд, домен,
выгорание, плюсы/минусы/красные флаги, вердикт) и тот же набор быстрых действий (Отклик /
Пропустить с причиной / Открыть в вебе), плюс хендофф в Скрининг/Техничку (те же `?vacancy=`
роуты веба, JS-D.1). Причины пропуска — канон `core/jobs/skip_reasons.py`, sync с фронтом/расширением.

Кнопки действий обрабатывает `bot_app.handlers.vacancy_actions`.
"""

from __future__ import annotations

from aiogram.types import InlineKeyboardButton, InlineKeyboardMarkup

from bot_app.config import get_bot_settings
from bot_app.utils import esc
from core.domains.opportunities.jobs import Job, resolve_job_source_group
from core.domains.opportunities.models import ScoreResult
from core.domains.opportunities.skip_reasons import SELF_SKIP_REASONS as SELF_REJECT_REASONS

REC_LABELS = {
    "strong_apply": "Сильный фит",
    "apply": "Подать",
    "maybe": "Сомнение",
    "skip": "Пропустить",
}
# Тон вердикта = RECOMMENDATION_TONE в shared/criteria.ts (чип PNG / расширение / веб).
REC_TONES: dict[str, str] = {
    "strong_apply": "strong",
    "apply": "good",
    "maybe": "mid",
    "skip": "bad",
}
# Цвета чипа = extension/src/ui/tokens.css (.jh-rec.* → --jh-pos/info/warn / slate).
REC_COLORS: dict[str, dict[str, str]] = {
    "strong_apply": {"bg": "#ecfdf5", "fg": "#047857", "border": "#a7f3d0"},
    "apply": {"bg": "#f0f9ff", "fg": "#0369a1", "border": "#bae6fd"},
    "maybe": {"bg": "#fffbeb", "fg": "#b45309", "border": "#fde68a"},
    "skip": {"bg": "#f8fafc", "fg": "#64748b", "border": "#e2e8f0"},
}
GRADE_LABELS = {
    "above": "Выше цели",
    "match": "В цель",
    "slightly_below": "Чуть ниже",
    "far_below": "Заметно ниже",
    "off_profile": "Не по профилю",
    # Легаси абсолютной шкалы (старые jsonb) - на случай сырого dict до coerce.
    "senior_plus": "Senior+",
    "mid": "Middle",
    "junior": "Junior",
    "generic_backend": "Generic",
    "wrong_domain_senior": "Senior+ (не тот домен)",
}
REMOTE_LABELS = {
    "ideal": "Идеал (весь мир)",
    "ok": "Ок (только РФ)",
    "risky": "Риск, уточнить",
    "blocker": "Офис/блокер",
}
BURNOUT_LABELS = {"low": "Низкий", "medium": "Средний", "high": "Высокий"}
SOURCE_GROUP_LABELS = {
    "hh": "hh",
    "getmatch": "getmatch",
    "habr": "habr",
    "tg": "Telegram",
}
COMPANY_TYPE_LABELS = {
    "product": "Продукт",
    "fintech_product": "Финтех-продукт",
    "bank": "Банк",
    "startup": "Стартап",
    "outsource": "Аутсорс",
    "infra": "Инфра",
    "unknown": "—",
}

_MAX_BULLETS = 4
# Telegram caption limit; короткая подпись PNG укладывается с запасом.
_CAPTION_MAX = 1024


def build_card_caption(job: Job, score: ScoreResult) -> str:
    """Короткая подпись к PNG: «Компания — роль · NN/100 · вердикт»."""
    company = (job.company or "компания не указана").strip()
    title = (job.title or "должность не указана").strip()
    rec = REC_LABELS.get(score.recommendation, score.recommendation)
    caption = f"{company} — {title} · {score.overall_score}/100 · {rec}"
    if len(caption) <= _CAPTION_MAX:
        return caption
    return caption[: _CAPTION_MAX - 1].rstrip() + "…"


def _bullets(items: list[str], emoji: str) -> list[str]:
    return [f"{emoji} {esc(item)}" for item in items[:_MAX_BULLETS]]


def _domain_label(score: ScoreResult) -> str:
    niches = score.role_content_match.matched_niche[:2]
    if niches:
        return ", ".join(niches)
    value = score.role_content_match.score
    if value >= 70:
        return "в нише"
    if value >= 40:
        return "частично"
    return "далёкий"


def _remote_label(score: ScoreResult) -> str:
    level = score.remote_abroad_compat.level
    return REMOTE_LABELS.get(level, level)


def _salary_line(job: Job, score: ScoreResult) -> str:
    text = (
        job.salary_text
        or score.salary.value_or_range
        or score.salary.estimated_range
        or "не указана"
    )
    check = " ✅" if score.salary.meets_min else ""
    return f"💰 {esc(text)}{check}"


def build_vacancy_card_text(
    job: Job,
    score: ScoreResult,
    header: str,
    *,
    status_note: str | None = None,
) -> str:
    """Карточка результата скоринга — без пересказа текста вакансии.

    `status_note` — опциональная строка внизу (проставляется после действия Отклик/Пропустить,
    см. `bot_app.handlers.vacancy_actions`).
    """
    rec = REC_LABELS.get(score.recommendation, score.recommendation)
    company = job.company or "компания не указана"
    position = job.title or "должность не указана"

    # M4: показываем источник не только для форвардов (header), но и как отдельную строку —
    # каноничная группа из jobs.source/vacancy_id, как в вебе.
    source_group = resolve_job_source_group(job.source, job.vacancy_id)
    source_label = SOURCE_GROUP_LABELS.get(source_group, source_group)

    lines = [
        header,
        "",
        f"📥 Источник: {esc(source_label)}",
        f"💼 <b>{esc(company)}</b> — {esc(position)}",
        f"📊 <b>{score.overall_score}/100</b> · {esc(rec)}",
        _salary_line(job, score),
        f"🌍 Удалёнка: {esc(_remote_label(score))}",
        "🎯 Грейд: " + esc(GRADE_LABELS.get(score.grade_match.level, score.grade_match.level)),
        f"🧩 Домен: {esc(_domain_label(score))}",
        "Управление: "
        + esc(BURNOUT_LABELS.get(score.burnout_risk.level, score.burnout_risk.level)),
        "🏢 Тип: " + esc(COMPANY_TYPE_LABELS.get(score.company_type, score.company_type)),
    ]
    if score.one_line_verdict:
        lines += ["", f"💬 {esc(score.one_line_verdict)}"]
    if score.pros:
        lines += ["", "<b>Плюсы:</b>", *_bullets(score.pros, "＋")]
    if score.red_flags:
        lines += ["", "<b>Красные флаги:</b>", *_bullets(score.red_flags, "🚩")]
    if score.cons:
        lines += ["", "<b>Минусы:</b>", *_bullets(score.cons, "－")]
    if status_note:
        lines += ["", status_note]
    return "\n".join(lines)


def _web_button(text: str, url: str) -> InlineKeyboardButton | None:
    """URL-кнопка на веб. Только https — Telegram отвергает inline-URL с localhost/http и ломает
    отправку (тот же принцип, что `bot_app.utils.keyboards._web_button`). В dev кнопки просто нет —
    открыть вакансию можно через /menu → «Открыть веб-дэшборд» (URL там даётся текстом).
    """
    url = url.strip()
    if url.startswith("https://"):
        return InlineKeyboardButton(text=text, url=url)
    return None


def _web_links_row(vacancy_id: str) -> list[InlineKeyboardButton]:
    web_url = get_bot_settings().web_url.rstrip("/")
    buttons = (
        _web_button("🌐 Веб", f"{web_url}/jobs/{vacancy_id}"),
        _web_button("🧩 Скрининг", f"{web_url}/screening?vacancy={vacancy_id}"),
        _web_button("🎯 Техничка", f"{web_url}/tech?vacancy={vacancy_id}"),
    )
    return [b for b in buttons if b is not None]


def build_vacancy_actions_keyboard(
    job: Job, *, skipped: bool = False, applied: bool = False
) -> InlineKeyboardMarkup:
    """Клавиатура действий под карточкой: Отклик/Пропустить (или их «отменить»), плюс веб-хендофф.

    После применения решения (apply/skip) верхний ряд подменяется на «отменить», чтобы случайный
    повторный клик не плодил дубли действий, но путь назад (вернуть в воронку) остаётся доступным.
    """
    rows: list[list[InlineKeyboardButton]] = []
    if job.id is not None:
        if skipped:
            rows.append(
                [
                    InlineKeyboardButton(
                        text="↩ Вернуть в воронку", callback_data=f"vac:unskip:{job.id}"
                    )
                ]
            )
        elif not applied:
            rows.append(
                [
                    InlineKeyboardButton(text="✅ Отклик", callback_data=f"vac:apply:{job.id}"),
                    InlineKeyboardButton(text="⛔ Пропустить", callback_data=f"vac:skip:{job.id}"),
                ]
            )
    if job.vacancy_id:
        links = _web_links_row(job.vacancy_id)
        if links:
            rows.append(links)
    return InlineKeyboardMarkup(inline_keyboard=rows)


def build_skip_reason_keyboard(job_id: int) -> InlineKeyboardMarkup:
    """Чипы причин пропуска (2 в ряд) + возврат к основным действиям."""
    rows: list[list[InlineKeyboardButton]] = []
    row: list[InlineKeyboardButton] = []
    for idx, reason in enumerate(SELF_REJECT_REASONS):
        row.append(InlineKeyboardButton(text=reason, callback_data=f"vac:skipr:{job_id}:{idx}"))
        if len(row) == 2:
            rows.append(row)
            row = []
    if row:
        rows.append(row)
    rows.append([InlineKeyboardButton(text="◀ Назад", callback_data=f"vac:back:{job_id}")])
    return InlineKeyboardMarkup(inline_keyboard=rows)
