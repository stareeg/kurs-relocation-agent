#!/usr/bin/env python3
"""Backfill `jobs.company_canonical` детерминированным нормализатором.

Без LLM (в отличие от normalize_company с allow_llm=True): исторический хвост и чужие машины
не должны тратить OpenRouter на разовую миграцию. Новые записи заполняются в `save_job`.

Использование:
    python -m core.domains.opportunities.companies.backfill              # применить
    python -m core.domains.opportunities.companies.backfill --dry-run    # только план
    python -m core.domains.opportunities.companies.backfill --force      # переписать уже заполненные каноны
"""

from __future__ import annotations

import asyncio
from collections import Counter

import click

from core.domains.opportunities.jobs import company_canonical_for
from core.platform.db.pool import create_pool


def plan_updates(
    rows: list[tuple[int, str | None, str | None]],
    *,
    force: bool,
) -> list[tuple[int, str | None, str | None]]:
    """(id, company, company_canonical) → список (id, new_canonical, old_canonical) к записи.

    Без --force трогаем только строки с пустым company_canonical. Пропуск, если канон
    уже совпадает с детерминированным результатом.
    """
    planned: list[tuple[int, str | None, str | None]] = []
    for job_id, company, current in rows:
        cur = (current or "").strip() or None
        if not force and cur is not None:
            continue
        new = company_canonical_for(company)
        if new == cur:
            continue
        planned.append((job_id, new, current))
    return planned


async def run(*, dry_run: bool, force: bool) -> None:
    pool = await create_pool()
    try:
        rows = await pool.fetch("select id, company, company_canonical from jobs order by id")
        triples = [(int(r["id"]), r["company"], r["company_canonical"]) for r in rows]
        planned = plan_updates(triples, force=force)

        if not planned:
            click.echo("Нечего бэкфилить — company_canonical уже актуален.")
            return

        by_canon: Counter[str] = Counter()
        for _, new, _ in planned:
            by_canon[new or "(null)"] += 1

        click.echo(f"К обновлению: {len(planned)} строк")
        for name, n in by_canon.most_common(20):
            click.echo(f"  {name}: {n}")
        if len(by_canon) > 20:
            click.echo(f"  … ещё {len(by_canon) - 20} канонов")

        if dry_run:
            for job_id, new, old in planned[:15]:
                click.echo(f"  id={job_id}: {old!r} → {new!r}")
            if len(planned) > 15:
                click.echo(f"  … и ещё {len(planned) - 15}")
            click.echo("\n--dry-run: в БД ничего не записано.")
            return

        async with pool.acquire() as conn, conn.transaction():
            for job_id, new, _old in planned:
                await conn.execute(
                    "update jobs set company_canonical = $2, updated_at = now() where id = $1",
                    job_id,
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
    help="Пересчитать и переписать уже заполненные company_canonical",
)
def main(dry_run: bool, force: bool) -> None:
    """Backfill jobs.company_canonical (без LLM)."""
    asyncio.run(run(dry_run=dry_run, force=force))


if __name__ == "__main__":
    main()
