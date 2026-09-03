#!/usr/bin/env python3
"""Backfill `skipped_vacancies.canonical_reason` детерминированным канонизатором.

Этап 7 §7.1 (plans/scoring_precision_2026_08_17.md, D17): до фикса `skipped.save_skipped`
часть путей (`skip_job` — kanban drag-to-«Пропущено», `_apply_archive_disposition` — «Диалог
закрыт») писала `canonical_reason = NULL`. Новые записи заполняются в `save_skipped` сразу;
этот скрипт — разовый бэкфилл исторического хвоста. Без LLM: `canonical_skip_reason` — чистая
функция, которая никогда не возвращает пусто, так что классифицировать нечего.

Использование:
    python -m core.domains.opportunities.skip_reasons_backfill              # применить
    python -m core.domains.opportunities.skip_reasons_backfill --dry-run    # только план
    python -m core.domains.opportunities.skip_reasons_backfill --force      # переписать все каноны
"""

from __future__ import annotations

import asyncio
from collections import Counter

import click

from core.domains.opportunities.skip_reasons import canonical_skip_reason
from core.platform.db.pool import create_pool


def plan_updates(
    rows: list[tuple[int, str, str | None]],
    *,
    force: bool,
) -> list[tuple[int, str, str | None]]:
    """(id, skip_reason, canonical_reason) → список (id, new_canonical, old_canonical) к записи.

    Без --force трогаем только строки с пустым canonical_reason. Пропуск, если канон уже
    совпадает с тем, что вывела бы `canonical_skip_reason`.
    """
    planned: list[tuple[int, str, str | None]] = []
    for row_id, skip_reason, current in rows:
        cur = (current or "").strip() or None
        if not force and cur is not None:
            continue
        new = canonical_skip_reason(skip_reason)
        if new == cur:
            continue
        planned.append((row_id, new, current))
    return planned


async def run(*, dry_run: bool, force: bool) -> None:
    pool = await create_pool()
    try:
        rows = await pool.fetch(
            "select id, skip_reason, canonical_reason from skipped_vacancies order by id"
        )
        triples = [(int(r["id"]), r["skip_reason"] or "", r["canonical_reason"]) for r in rows]
        planned = plan_updates(triples, force=force)

        if not planned:
            click.echo("Нечего бэкфилить — canonical_reason уже актуален.")
            return

        by_canon: Counter[str] = Counter()
        for _, new, _ in planned:
            by_canon[new] += 1

        click.echo(f"К обновлению: {len(planned)} строк")
        for name, n in by_canon.most_common(20):
            click.echo(f"  {name}: {n}")

        if dry_run:
            for row_id, new, old in planned[:15]:
                click.echo(f"  id={row_id}: {old!r} → {new!r}")
            if len(planned) > 15:
                click.echo(f"  … и ещё {len(planned) - 15}")
            click.echo("\n--dry-run: в БД ничего не записано.")
            return

        async with pool.acquire() as conn, conn.transaction():
            for row_id, new, _old in planned:
                await conn.execute(
                    "update skipped_vacancies set canonical_reason = $2 where id = $1",
                    row_id,
                    new,
                )
        click.echo(f"\nГотово: обновлено {len(planned)} строк.")
    finally:
        await pool.close()


@click.command()
@click.option("--dry-run", is_flag=True, help="Только показать план, не писать в БД")
@click.option(
    "--force",
    is_flag=True,
    help="Пересчитать и переписать уже заполненные canonical_reason",
)
def main(dry_run: bool, force: bool) -> None:
    """Backfill skipped_vacancies.canonical_reason (без LLM)."""
    asyncio.run(run(dry_run=dry_run, force=force))


if __name__ == "__main__":
    main()
