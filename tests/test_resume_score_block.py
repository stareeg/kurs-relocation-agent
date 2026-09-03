"""Регрессия бага чата по резюме: `_resume_score_block` падал на слабом буллете без reason.

При regex-fallback (`find_weak_bullets`) `WeakBullet.reason` остаётся `None`, и строка
`getattr(w, "reason", "").strip()` роняла `AttributeError: 'NoneType' object has no attribute
'strip'` — ещё до вызова LLM, поэтому реплики чата вообще не персистились (лента `resume_chat_
messages` оставалась пустой, а композер показывал ошибку вместо ответа).
"""

from __future__ import annotations

from core.domains.assistant.service import _resume_score_block
from core.domains.profile.gap import (
    ResumeGapReport,
    ResumeScoreBreakdown,
    WeakBullet,
)


def _report_with_weak_bullets(*bullets: WeakBullet) -> ResumeGapReport:
    score = ResumeScoreBreakdown(
        total=50,
        structure=60,
        market_coverage=None,
        writing=40,
        role_fit=50,
        weak_bullets=list(bullets),
    )
    return ResumeGapReport(available=False, corpus_size=0, score=score)


def test_resume_score_block_handles_weak_bullet_without_reason() -> None:
    """Regex-weak bullet (`reason=None`) не должен ронять сборку блока балла."""
    report = _report_with_weak_bullets(
        WeakBullet(section="experience", ref="Сбер — Lead", text="Занимался развитием команды"),
    )
    block = _resume_score_block(report)
    assert "Слабые буллеты" in block
    assert "Занимался развитием команды" in block
    # reason=None → без суффикса « — …», но без исключения.
    assert "None" not in block


def test_resume_score_block_handles_weak_bullet_with_reason() -> None:
    """LLM-weak bullet с reason — суффикс подставляется как раньше."""
    report = _report_with_weak_bullets(
        WeakBullet(
            section="about",
            ref="Обо мне",
            text="Ответственный и коммуникабельный",
            reason="нет цифры и глагола",
        ),
    )
    block = _resume_score_block(report)
    assert "— нет цифры и глагола" in block
