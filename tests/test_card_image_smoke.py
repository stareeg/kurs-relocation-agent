"""TB-5.6: smoke PNG-карточки — magic bytes, кириллица, sparse-поля. Без пиксельных голденов."""

from __future__ import annotations

import io
import struct

from PIL import Image

from bot_app.services.card_image import _CARD_H, _CARD_W, render_score_card
from core.domains.opportunities.jobs import Job
from core.domains.opportunities.models import (
    BurnoutRisk,
    CompanyFit,
    GradeMatch,
    RemoteAbroadCompat,
    RoleContentMatch,
    SalaryInfo,
    ScoreResult,
)
from core.domains.opportunities.score_breakdown import compute_score_breakdown

_PNG_MAGIC = b"\x89PNG\r\n\x1a\n"


def _job(**kwargs: object) -> Job:
    base: dict[str, object] = {
        "vacancy_text": "текст",
        "company": "Яндекс",
        "title": "Руководитель продукта",
        "source": "hh",
        "vacancy_id": "123456",
        "salary_text": "350–450 тыс. ₽",
    }
    base.update(kwargs)
    return Job(**base)  # type: ignore[arg-type]


def _score(**overrides: object) -> ScoreResult:
    data: dict[str, object] = {
        "overall_score": 88,
        "recommendation": "strong_apply",
        "remote_abroad_compat": RemoteAbroadCompat(level="ideal", reasoning="весь мир"),
        "grade_match": GradeMatch(level="match", reasoning="в цель"),
        "salary": SalaryInfo(meets_min=True, value_or_range="350–450k", note=""),
        "role_content_match": RoleContentMatch(
            score=85, matched_niche=["финтех"], reasoning="ниша"
        ),
        "burnout_risk": BurnoutRisk(level="medium", reasoning="смесь"),
        "company_fit": CompanyFit(level="strong", reasoning="ок"),
        "company_type": "product",
        "pros": ["Сильный домен", "Удалёнка ОК", "Вилка выше цели"],
        "cons": ["Много процессов"],
        "red_flags": ["Стек устарел", "Частые дежурства"],
        "one_line_verdict": "Сильный фит: домен и вилка совпали",
    }
    data.update(overrides)
    score = ScoreResult(**data)  # type: ignore[arg-type]
    score.score_breakdown = compute_score_breakdown(score)
    return score


def _assert_valid_png(png: bytes) -> Image.Image:
    assert png[:8] == _PNG_MAGIC, png[:16]
    assert len(png) > 0
    img = Image.open(io.BytesIO(png))
    img.load()
    assert img.format == "PNG"
    assert img.size == (_CARD_W, _CARD_H)
    return img


def test_render_score_card_valid_png() -> None:
    png = render_score_card(_job(), _score())
    _assert_valid_png(png)
    assert len(png) > 1_000


def test_render_score_card_cyrillic_ok() -> None:
    job = _job(
        company="ООО «Ромашка»",
        title="Ведущий продуктовый менеджер / Product Lead",
        salary_text="от 400 тыс. ₽ на руки",
    )
    score = _score(
        one_line_verdict="Хороший фит по грейду и удалёнке — стоит подать",
        pros=["Кириллица: зарплата", "Формат — весь мир", "Компания знакома"],
        red_flags=["Риск: много встреч", "Слабый бренд работодателя"],
    )
    png = render_score_card(job, score)
    _assert_valid_png(png)


def test_render_score_card_sparse_fields_ok() -> None:
    """Без зарплаты / вердикта / флагов / breakdown в jsonb — layout не ломается."""
    job = _job(salary_text=None, company=None, title=None)
    score = _score(
        salary=SalaryInfo(meets_min=False, value_or_range="", estimated_range="", note=""),
        one_line_verdict="",
        pros=["один плюс"],
        cons=["один минус"],
        red_flags=[],
        recommendation="skip",
        overall_score=22,
    )
    score.score_breakdown = {}
    png = render_score_card(job, score)
    img = _assert_valid_png(png)
    # Размер кадра фиксирован даже при пустых блоках.
    assert img.width == 1200 and img.height == 675


def test_render_score_card_all_recommendations() -> None:
    """Все четыре вердикта рисуются (чип/цвета) без падений."""
    for rec in ("strong_apply", "apply", "maybe", "skip"):
        png = render_score_card(_job(), _score(recommendation=rec, overall_score=50))
        assert png[:8] == _PNG_MAGIC


def test_png_ihdr_matches_canvas() -> None:
    """IHDR совпадает с 1200×675 — защита от случайного ресайза при save."""
    png = render_score_card(_job(), _score())
    assert png[12:16] == b"IHDR"
    width, height = struct.unpack(">II", png[16:24])
    assert (width, height) == (_CARD_W, _CARD_H)
