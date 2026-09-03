"""Трек поиска: основная vs дополнительная занятость.

Ось ортогональна `SearchMode` (интенсивность: active/passive) и `market_scope`
(география рынка). Используют шесть доменов — shared kernel, без доменной логики.
"""

from __future__ import annotations

from typing import Literal

SearchTrack = Literal["primary", "second_job"]

#: Русские подписи — канон продукта (по образцу career.search_state.MODE_LABELS).
TRACK_LABELS: dict[SearchTrack, str] = {
    "primary": "Основная",
    "second_job": "Дополнительная",
}

DEFAULT_TRACK: SearchTrack = "primary"

DEFAULT_TRACKS: tuple[SearchTrack, ...] = (DEFAULT_TRACK,)

SEARCH_TRACKS: tuple[SearchTrack, ...] = ("primary", "second_job")


def normalize_tracks(tracks: list[str] | tuple[str, ...] | None) -> list[SearchTrack]:
    """Канон набора: `primary` всегда внутри, `second_job` — опционально, порядок стабилен.

    Неизвестные значения отбрасываются. Пустой/битый вход → только основная работа.
    """
    wanted = {t for t in (tracks or ()) if t in TRACK_LABELS}
    out: list[SearchTrack] = [DEFAULT_TRACK]
    if "second_job" in wanted:
        out.append("second_job")
    return out


def track_labels(tracks: list[SearchTrack] | tuple[SearchTrack, ...]) -> list[str]:
    return [TRACK_LABELS[t] for t in tracks]


__all__ = [
    "DEFAULT_TRACK",
    "DEFAULT_TRACKS",
    "SEARCH_TRACKS",
    "TRACK_LABELS",
    "SearchTrack",
    "normalize_tracks",
    "track_labels",
]
