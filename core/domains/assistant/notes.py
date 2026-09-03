"""Repository заметок-шпаргалок: CRUD + полнотекстовый поиск, без эмбеддингов.

Свободное знание владельца общего назначения (не привязано к вакансии, в отличие от `job_notes` -
поле `note` в `jobs`) - формулировки про уход из компании, свои шпаргалки по темам, и т.п.
Осознанно дешёвое хранилище: обычная таблица + Postgres `tsvector`, без эмбеддингов,
вектора и реранка.

Два способа найти заметки:
- `search_notes` - явный поиск владельца по строке в UI: `websearch_to_tsquery` (понимает
  "фразы в кавычках", `или`/`-исключение` как в вебе), ранжирование `ts_rank`.
- `top_notes_for_topic` - подмешивание в LLM-контекст (Q&A по вакансии/тренажёр): текущий
  вопрос/сообщение - целое предложение, а не короткий запрос, поэтому `websearch_to_tsquery`
  (по умолчанию трактует слова через AND) почти никогда не совпадёт с короткой заметкой целиком.
  Вместо этого собираем OR-запрос из ключевых слов темы - редкое совпадение хотя бы одного слова
  всё равно даёт релевантную заметку, а `ts_rank` расставляет более совпадающие выше. Только заметки
  с `use_in_rag=true`.

M4 (plans/multitenancy_gaps_2026_08_06.md §3.4): все функции принимают account_id — заметка
одного аккаунта не должна быть видна/редактируема/подмешана в промпт другому (0105).
"""

from __future__ import annotations

import re
from datetime import datetime

from pydantic import BaseModel, Field

from core.platform.db.pool import Executor, get_pool, row_to_dict

_COLS = "id, title, body, tags, use_in_rag, created_at, updated_at"
# Слова короче 3 символов почти всегда шум (предлоги/союзы) - не годятся как поисковые термы.
_MIN_WORD_LEN = 3
_MAX_TOPIC_WORDS = 12
_WORD_RE = re.compile(r"[а-яёa-z0-9]+", re.IGNORECASE)


class Note(BaseModel):
    """Одна заметка: заголовок, markdown-тело, теги, тумблер использования в LLM-контексте."""

    id: int | None = None
    title: str = ""
    body: str = ""
    tags: list[str] = Field(default_factory=list)
    use_in_rag: bool = True
    created_at: datetime | None = None
    updated_at: datetime | None = None


class NoteMessage(BaseModel):
    """Одно сообщение контекста (UX7): контекст выглядит как чат — только реплики владельца,
    без ответа ассистента. `notes.body` держится репозиторием как конкатенация этих сообщений."""

    id: int | None = None
    note_id: int
    body: str = ""
    created_at: datetime | None = None


def _topic_tsquery(topic: str) -> str | None:
    """Ключевые слова темы → строка `слово1 | слово2 | ...` для `to_tsquery`. Пусто → None."""
    words = _WORD_RE.findall(topic.lower())
    seen: list[str] = []
    for w in words:
        if len(w) < _MIN_WORD_LEN:
            continue
        if w not in seen:
            seen.append(w)
        if len(seen) >= _MAX_TOPIC_WORDS:
            break
    if not seen:
        return None
    return " | ".join(seen)


async def create_note(
    title: str,
    body: str,
    tags: list[str] | None = None,
    *,
    use_in_rag: bool = True,
    account_id: int,
    db: Executor | None = None,
) -> Note:
    db = db or get_pool()
    row = await db.fetchrow(
        "insert into notes (account_id, title, body, tags, use_in_rag) values ($1, $2, $3, $4, $5) "
        f"returning {_COLS}",
        account_id,
        title.strip(),
        body,
        tags or [],
        use_in_rag,
    )
    assert row is not None  # insert ... returning всегда отдаёт строку
    return Note(**row_to_dict(row))


async def list_notes(*, account_id: int, db: Executor | None = None) -> list[Note]:
    """Все заметки аккаунта, свежепрочитанные/изменённые первыми."""
    db = db or get_pool()
    rows = await db.fetch(
        f"select {_COLS} from notes where account_id = $1 order by updated_at desc, id desc",
        account_id,
    )
    return [Note(**row_to_dict(r)) for r in rows]


async def get_note(note_id: int, *, account_id: int, db: Executor | None = None) -> Note | None:
    db = db or get_pool()
    row = await db.fetchrow(
        f"select {_COLS} from notes where id = $1 and account_id = $2", note_id, account_id
    )
    return Note(**row_to_dict(row)) if row is not None else None


async def update_note(
    note_id: int,
    *,
    title: str | None = None,
    body: str | None = None,
    tags: list[str] | None = None,
    use_in_rag: bool | None = None,
    account_id: int,
    db: Executor | None = None,
) -> Note | None:
    """Правка по id (None = не менять). Нет заметки/чужая → None (роутер отдаст 404)."""
    db = db or get_pool()
    row = await db.fetchrow(
        "update notes set "
        "title = coalesce($3, title), "
        "body = coalesce($4, body), "
        "tags = coalesce($5, tags), "
        "use_in_rag = coalesce($6, use_in_rag), "
        "updated_at = now() "
        f"where id = $1 and account_id = $2 returning {_COLS}",
        note_id,
        account_id,
        title,
        body,
        tags,
        use_in_rag,
    )
    return Note(**row_to_dict(row)) if row is not None else None


async def delete_note(note_id: int, *, account_id: int, db: Executor | None = None) -> bool:
    db = db or get_pool()
    result = await db.execute(
        "delete from notes where id = $1 and account_id = $2", note_id, account_id
    )
    return str(result).rsplit(" ", 1)[-1] not in ("", "0")


_MESSAGE_COLS = "id, note_id, body, created_at"


async def _sync_note_body(note_id: int, *, account_id: int, db: Executor) -> None:
    """`notes.body` = сообщения контекста через "\n\n" — держит generated `search_vector`
    (0029_notes) и RAG-подмешивание (`build_notes_context_block`) в синхроне с моделью сообщений,
    не трогая ни то, ни другое."""
    rows = await db.fetch(
        "select body from note_messages where note_id = $1 and account_id = $2 order by id",
        note_id,
        account_id,
    )
    body = "\n\n".join(r["body"] for r in rows)
    await db.execute(
        "update notes set body = $3, updated_at = now() where id = $1 and account_id = $2",
        note_id,
        account_id,
        body,
    )


async def list_note_messages(
    note_id: int, *, account_id: int, db: Executor | None = None
) -> list[NoteMessage]:
    """Лента сообщений контекста, старые сверху (как реплики в диалоге вакансии)."""
    db = db or get_pool()
    rows = await db.fetch(
        f"select {_MESSAGE_COLS} from note_messages where note_id = $1 and account_id = $2 "
        "order by id",
        note_id,
        account_id,
    )
    return [NoteMessage(**row_to_dict(r)) for r in rows]


async def add_note_message(
    note_id: int, body: str, *, account_id: int, db: Executor | None = None
) -> NoteMessage | None:
    """Добавить сообщение в контекст (композер «Новый контекст» / кнопка отправки).

    M4: `insert ... select ... where exists(нота этого аккаунта)` — атомарная проверка владения,
    не отдельный SELECT + INSERT (иначе окно гонки/риск подставить чужой account_id). Нет заметки
    или заметка чужая → None (роутер отдаст 404, не 500 на FK-нарушении).
    """
    db = db or get_pool()
    row = await db.fetchrow(
        "insert into note_messages (account_id, note_id, body) "
        "select $2, n.id, $3 from notes n where n.id = $1 and n.account_id = $2 "
        f"returning {_MESSAGE_COLS}",
        note_id,
        account_id,
        body,
    )
    if row is None:
        return None
    await _sync_note_body(note_id, account_id=account_id, db=db)
    return NoteMessage(**row_to_dict(row))


async def update_note_message(
    note_id: int, message_id: int, body: str, *, account_id: int, db: Executor | None = None
) -> NoteMessage | None:
    """Правка одного сообщения (клик по сообщению → редактирование). Нет строки/чужая → None."""
    db = db or get_pool()
    row = await db.fetchrow(
        "update note_messages set body = $4 "
        "where id = $2 and note_id = $1 and account_id = $3 "
        f"returning {_MESSAGE_COLS}",
        note_id,
        message_id,
        account_id,
        body,
    )
    if row is None:
        return None
    await _sync_note_body(note_id, account_id=account_id, db=db)
    return NoteMessage(**row_to_dict(row))


async def delete_note_message(
    note_id: int, message_id: int, *, account_id: int, db: Executor | None = None
) -> bool:
    """Удалить одно сообщение контекста. True — строка была (и принадлежала аккаунту)."""
    db = db or get_pool()
    row = await db.fetchrow(
        "delete from note_messages where id = $1 and note_id = $2 and account_id = $3 returning id",
        message_id,
        note_id,
        account_id,
    )
    if row is None:
        return False
    await _sync_note_body(note_id, account_id=account_id, db=db)
    return True


async def search_notes(
    query: str, limit: int = 20, *, account_id: int, db: Executor | None = None
) -> list[Note]:
    """Явный поиск владельца (websearch-синтаксис: "фразы", ИЛИ, -исключение), топ по ts_rank."""
    query = query.strip()
    if not query:
        return await list_notes(account_id=account_id, db=db)
    db = db or get_pool()
    rows = await db.fetch(
        "select "
        f"{_COLS}, ts_rank(search_vector, websearch_to_tsquery('russian', $1)) as rank "
        "from notes where account_id = $2 "
        "and search_vector @@ websearch_to_tsquery('russian', $1) "
        "order by rank desc, updated_at desc limit $3",
        query,
        account_id,
        max(1, min(limit, 200)),
    )
    return [Note(**{k: v for k, v in row_to_dict(r).items() if k != "rank"}) for r in rows]


async def top_notes_for_topic(
    topic: str, limit: int = 3, *, account_id: int, db: Executor | None = None
) -> list[Note]:
    """Top-K заметок (`use_in_rag=true`) по простому текстовому совпадению с темой/вопросом.

    Не эмбеддинги - ключевые слова темы через OR (см. `_topic_tsquery`), ранжирование `ts_rank`.
    Пустая тема / без ключевых слов / нет совпадений → пустой список (контекст не подмешивается).
    """
    tsquery = _topic_tsquery(topic)
    if tsquery is None:
        return []
    db = db or get_pool()
    rows = await db.fetch(
        "select "
        f"{_COLS}, ts_rank(search_vector, to_tsquery('russian', $1)) as rank "
        "from notes where account_id = $2 and use_in_rag "
        "and search_vector @@ to_tsquery('russian', $1) "
        "order by rank desc, updated_at desc limit $3",
        tsquery,
        account_id,
        max(1, min(limit, 20)),
    )
    return [Note(**{k: v for k, v in row_to_dict(r).items() if k != "rank"}) for r in rows]


async def get_notes_by_ids(
    note_ids: list[int], *, account_id: int, db: Executor | None = None
) -> list[Note]:
    """Точные заметки по списку id (явный выбор контекста для чата). Пропускает неизвестные/чужие id.

    Сохраняет порядок входного списка. Не фильтрует по `use_in_rag` — явный выбор владельца
    сильнее тумблера (он может хотеть прикрепить даже «выключенную из RAG» заметку).
    """
    if not note_ids:
        return []
    db = db or get_pool()
    # in(...) с параметризованным list — asyncpg не принимает list напрямую в IN, разворачиваем
    # через `= any($1::int[])`.
    rows = await db.fetch(
        f"select {_COLS} from notes where id = any($1::int[]) and account_id = $2",
        list(note_ids),
        account_id,
    )
    by_id = {row["id"]: Note(**row_to_dict(row)) for row in rows}
    return [by_id[i] for i in note_ids if i in by_id]


def build_notes_context_block(notes: list[Note]) -> str:
    """Заметки → текстовый блок промпта. Пусто на входе → пустая строка (блок не вставляем)."""
    if not notes:
        return ""
    lines = ["--- Заметки владельца (могут быть релевантны) ---"]
    for n in notes:
        header = n.title.strip() or "без названия"
        if n.tags:
            header += f" [{', '.join(n.tags)}]"
        lines.append(f"### {header}\n{n.body.strip()}")
    return "\n\n".join(lines)


async def notes_context_block_for_topic(topic: str, limit: int = 3, *, account_id: int) -> str:
    """Best-effort обёртка `top_notes_for_topic` + `build_notes_context_block` для промптов чата/
    тренажёра: нет PG / нет совпадений → тихо пустая строка, вызывающий код не должен думать про
    try/except на каждом месте подключения (Q&A по вакансии, тренажёр JS-12).
    """
    try:
        notes = await top_notes_for_topic(topic, limit, account_id=account_id)
    except Exception:  # noqa: BLE001 — нет PG/таблицы → просто без заметок в контексте
        return ""
    return build_notes_context_block(notes)


__all__ = [
    "Note",
    "NoteMessage",
    "add_note_message",
    "build_notes_context_block",
    "create_note",
    "delete_note",
    "delete_note_message",
    "get_note",
    "get_notes_by_ids",
    "list_note_messages",
    "list_notes",
    "notes_context_block_for_topic",
    "search_notes",
    "top_notes_for_topic",
    "update_note",
    "update_note_message",
]
