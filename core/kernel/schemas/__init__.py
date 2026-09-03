"""Общие кросс-доменные таксономии (shared kernel): используются 3+ доменами, без доменных
импортов и I/O. Однодоменные типы живут в `models.py` своего домена, не здесь.

Импорт — по подмодулям: `from core.kernel.schemas.funnel import FunnelStatus`,
`from core.kernel.schemas.track import SearchTrack`.
"""
