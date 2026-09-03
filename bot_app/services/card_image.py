"""PNG-карточка скоринга для Telegram.

Чистый рендер уже посчитанного ``ScoreResult`` — без LLM. Палитра и тон вердикта
совпадают с панелью расширения (``shared/criteria.ts`` + ``extension/src/ui/tokens.css``);
шрифты только из ``bot_app/assets/fonts/`` (friend-install без системных путей).
"""

from __future__ import annotations

import io
from pathlib import Path

from PIL import Image, ImageDraw, ImageFont
from PIL.ImageFont import FreeTypeFont

from bot_app.services.vacancy_card import (
    REC_COLORS,
    REC_LABELS,
    SOURCE_GROUP_LABELS,
)
from core.domains.opportunities.jobs import Job, resolve_job_source_group
from core.domains.opportunities.models import ScoreResult
from core.domains.opportunities.score_breakdown import (
    DEFAULT_WEIGHTS,
    compute_score_breakdown,
)

# Канон подписей = SCORE_BREAKDOWN_LABEL в shared/criteria.ts.
SCORE_BREAKDOWN_LABEL: dict[str, str] = {
    "salary": "Зарплата",
    "work_format": "Формат",
    "grade_match": "Грейд",
    "role_content": "Домен",
    "management": "Роль",
    "company": "Компания",
}

# Заливки полос = .jh-breakdown-fill.* / --jh-dot-* в tokens.css.
_TONE_FILL: dict[str, str] = {
    "good": "#10b981",
    "mid": "#f59e0b",
    "bad": "#f43f5e",
    "neutral": "#94a3b8",
}

_GRADE_TONE = {
    "match": "good",
    "above": "mid",
    "slightly_below": "mid",
    "far_below": "bad",
    "off_profile": "bad",
}
_REMOTE_TONE = {"ideal": "good", "ok": "neutral", "risky": "mid", "blocker": "bad"}
_MANAGEMENT_TONE = {"low": "good", "medium": "mid", "high": "bad"}
_COMPANY_FIT_TONE = {"strong": "good", "ok": "neutral", "weak": "bad", "unknown": "neutral"}

_CARD_W = 1200
_CARD_H = 675
_PAD = 48
_BG = "#ffffff"
_FG = "#0f172a"
_BODY = "#334155"
_MUTED = "#64748b"
_META = "#94a3b8"
_TRACK = "#f1f5f9"
_BORDER = "#e2e8f0"
_PRO_DOT = "#10b981"
_FLAG_DOT = "#f43f5e"

_FONTS_DIR = Path(__file__).resolve().parent.parent / "assets" / "fonts"
_MAX_PROS = 3
_MAX_FLAGS = 3


def _hex_rgb(value: str) -> tuple[int, int, int]:
    h = value.lstrip("#")
    return int(h[0:2], 16), int(h[2:4], 16), int(h[4:6], 16)


def _font(filename: str, size: int) -> FreeTypeFont:
    return ImageFont.truetype(str(_FONTS_DIR / filename), size)


def _fit(draw: ImageDraw.ImageDraw, text: str, font: FreeTypeFont, max_w: float) -> str:
    if not text:
        return text
    if draw.textlength(text, font=font) <= max_w:
        return text
    ell = "…"
    lo, hi = 0, len(text)
    while lo < hi:
        mid = (lo + hi) // 2
        candidate = text[:mid].rstrip() + ell
        if draw.textlength(candidate, font=font) <= max_w:
            lo = mid + 1
        else:
            hi = mid
    cut = max(0, lo - 1)
    return text[:cut].rstrip() + ell if cut else ell


def _score_fg(overall: int) -> str:
    # scoreLevel из shared/criteria.ts: ≥80 good, ≥60 mid, иначе low.
    if overall >= 80:
        return "#047857"
    if overall >= 60:
        return "#b45309"
    return "#64748b"


def _salary_tone(score: ScoreResult) -> str:
    has_value = bool(score.salary.value_or_range or score.salary.estimated_range)
    if score.salary.meets_min:
        return "good"
    return "bad" if has_value else "neutral"


def _role_content_tone(value: int | None) -> str:
    if value is None:
        return "neutral"
    if value >= 70:
        return "good"
    if value >= 40:
        return "mid"
    return "bad"


def breakdown_tone(key: str, score: ScoreResult) -> str:
    """Тон критерия = scoreBreakdownTone в shared/criteria.ts."""
    if key == "salary":
        return _salary_tone(score)
    if key == "work_format":
        return _REMOTE_TONE.get(score.remote_abroad_compat.level, "neutral")
    if key == "grade_match":
        return _GRADE_TONE.get(score.grade_match.level, "neutral")
    if key == "role_content":
        return _role_content_tone(score.role_content_match.score)
    if key == "management":
        return _MANAGEMENT_TONE.get(score.burnout_risk.level, "neutral")
    if key == "company":
        return _COMPANY_FIT_TONE.get(score.company_fit.level, "neutral")
    return "neutral"


def _resolved_breakdown(score: ScoreResult) -> dict[str, int]:
    bd = score.score_breakdown or {}
    if all(isinstance(bd.get(k), int) for k in DEFAULT_WEIGHTS):
        return {k: int(bd[k]) for k in DEFAULT_WEIGHTS}
    return compute_score_breakdown(score)


def _salary_text(job: Job, score: ScoreResult) -> str:
    return (
        (job.salary_text or "").strip()
        or (score.salary.value_or_range or "").strip()
        or (score.salary.estimated_range or "").strip()
        or "не указана"
    )


def _rounded_chip(
    draw: ImageDraw.ImageDraw,
    xy: tuple[int, int],
    text: str,
    font: FreeTypeFont,
    colors: dict[str, str],
) -> int:
    """Рисует чип, возвращает правый край (x)."""
    pad_x, pad_y = 14, 8
    tw = draw.textlength(text, font=font)
    bbox = draw.textbbox((0, 0), text, font=font)
    th = bbox[3] - bbox[1]
    x0, y0 = xy
    x1 = int(x0 + tw + pad_x * 2)
    y1 = y0 + th + pad_y * 2
    draw.rounded_rectangle(
        (x0, y0, x1, y1),
        radius=10,
        fill=_hex_rgb(colors["bg"]),
        outline=_hex_rgb(colors["border"]),
        width=2,
    )
    draw.text((x0 + pad_x, y0 + pad_y - 1), text, font=font, fill=_hex_rgb(colors["fg"]))
    return x1


def render_score_card(job: Job, score: ScoreResult) -> bytes:
    """PNG ~1200×675: шапка, скор+чип, 6 полос, зарплата/вердикт, плюсы/флаги."""
    img = Image.new("RGB", (_CARD_W, _CARD_H), _hex_rgb(_BG))
    draw = ImageDraw.Draw(img)

    font_title = _font("Inter-Bold.ttf", 32)
    font_meta = _font("Inter-Regular.ttf", 20)
    font_score = _font("Inter-Bold.ttf", 72)
    font_chip = _font("Inter-Bold.ttf", 22)
    font_label = _font("Inter-Regular.ttf", 20)
    font_bar_num = _font("Inter-Bold.ttf", 18)
    font_body = _font("Inter-Regular.ttf", 22)
    font_bullet = _font("Inter-Regular.ttf", 20)

    company = (job.company or "компания не указана").strip()
    title = (job.title or "должность не указана").strip()
    source_group = resolve_job_source_group(job.source, job.vacancy_id)
    source_label = SOURCE_GROUP_LABELS.get(source_group, source_group)

    # --- Шапка ---
    header = f"{company} — {title}"
    source_w = draw.textlength(source_label, font=font_meta)
    header_max = _CARD_W - 2 * _PAD - source_w - 24
    header = _fit(draw, header, font_title, header_max)
    draw.text((_PAD, _PAD), header, font=font_title, fill=_hex_rgb(_FG))
    draw.text(
        (_CARD_W - _PAD - source_w, _PAD + 8),
        source_label,
        font=font_meta,
        fill=_hex_rgb(_MUTED),
    )

    # --- Скор + чип ---
    y_score = _PAD + 56
    score_text = f"{score.overall_score}/100"
    score_fill = _hex_rgb(_score_fg(score.overall_score))
    draw.text((_PAD, y_score), score_text, font=font_score, fill=score_fill)
    score_w = draw.textlength(score_text, font=font_score)
    rec = score.recommendation
    chip_label = REC_LABELS.get(rec, rec)
    colors = REC_COLORS.get(rec, REC_COLORS["skip"])
    chip_y = y_score + 22
    _rounded_chip(draw, (int(_PAD + score_w + 28), chip_y), chip_label, font_chip, colors)

    # --- 6 полос брейкдауна ---
    breakdown = _resolved_breakdown(score)
    rows = sorted(
        (
            (
                key,
                SCORE_BREAKDOWN_LABEL[key],
                breakdown[key],
                DEFAULT_WEIGHTS[key],
                breakdown_tone(key, score),
            )
            for key in DEFAULT_WEIGHTS
        ),
        key=lambda r: r[2],
        reverse=True,
    )

    y = y_score + 100
    label_col_w = 130
    num_col_w = 70
    bar_x0 = _PAD + label_col_w + 12
    bar_x1 = _CARD_W - _PAD - num_col_w - 8
    bar_h = 14
    row_gap = 36

    for _key, label, value, vmax, tone in rows:
        draw.text((_PAD, y - 2), label, font=font_label, fill=_hex_rgb(_BODY))
        draw.rounded_rectangle(
            (bar_x0, y + 4, bar_x1, y + 4 + bar_h),
            radius=7,
            fill=_hex_rgb(_TRACK),
        )
        frac = 0.0 if vmax <= 0 else max(0.0, min(1.0, value / vmax))
        fill_w = int((bar_x1 - bar_x0) * frac)
        if fill_w > 0:
            draw.rounded_rectangle(
                (bar_x0, y + 4, bar_x0 + fill_w, y + 4 + bar_h),
                radius=7,
                fill=_hex_rgb(_TONE_FILL.get(tone, _TONE_FILL["neutral"])),
            )
        nums = f"{value}/{vmax}"
        nums_w = draw.textlength(nums, font=font_bar_num)
        draw.text(
            (_CARD_W - _PAD - nums_w, y - 1),
            nums,
            font=font_bar_num,
            fill=_hex_rgb(_BODY),
        )
        y += row_gap

    # --- Зарплата + вердикт ---
    y += 8
    draw.line((_PAD, y, _CARD_W - _PAD, y), fill=_hex_rgb(_BORDER), width=1)
    y += 18
    salary = _salary_text(job, score)
    sal_tone = _salary_tone(score)
    sal_fg = {
        "good": "#047857",
        "bad": "#be123c",
        "neutral": _MUTED,
    }.get(sal_tone, _MUTED)
    verdict = (score.one_line_verdict or "").strip()
    line = f"{salary} · {verdict}" if verdict else salary
    line = _fit(draw, line, font_body, _CARD_W - 2 * _PAD)
    draw.text((_PAD, y), line, font=font_body, fill=_hex_rgb(sal_fg if not verdict else _BODY))

    # --- Плюсы / красные флаги (до 3) ---
    y += 40
    col_w = (_CARD_W - 2 * _PAD - 24) // 2
    pros = [p.strip() for p in score.pros if p and p.strip()][:_MAX_PROS]
    flags = [f.strip() for f in score.red_flags if f and f.strip()][:_MAX_FLAGS]

    def _bullets(items: list[str], x0: int, y0: int, dot: str) -> None:
        yy = y0
        for item in items:
            text = _fit(draw, item, font_bullet, col_w - 22)
            draw.ellipse((x0, yy + 7, x0 + 8, yy + 15), fill=_hex_rgb(dot))
            draw.text((x0 + 16, yy), text, font=font_bullet, fill=_hex_rgb(_BODY))
            yy += 28

    _bullets(pros, _PAD, y, _PRO_DOT)
    _bullets(flags, _PAD + col_w + 24, y, _FLAG_DOT)

    buf = io.BytesIO()
    img.save(buf, format="PNG", optimize=True)
    return buf.getvalue()
