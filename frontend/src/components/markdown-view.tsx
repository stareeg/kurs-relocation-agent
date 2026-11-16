import { Fragment, useEffect, useId, useMemo, useState, type ReactNode } from "react"
import katex from "katex"
import DOMPurify from "dompurify"
import { Skeleton } from "@/components/ui/skeleton"

// Рендер markdown под текстовые вкладки (резюме/легенда/заметки/скрининги) и чаты системы (JS-20):
// заголовки, списки, абзацы, инлайн-**жирный**/==хайлайт==/$формула$, код-блоки, KaTeX-формулы,
// Mermaid-диаграммы. Не тянем react-markdown/remark — тексты по структуре простые, свой парсер
// держит вывод в дизайн-дисциплине (токены foreground/muted-foreground) и не тащит лишний вес
// ради пары вкладок.

// ---------- KaTeX (best-effort, невалидная формула → голый текст, не падаем и не показываем мусор) ----------

function tryKatex(tex: string, displayMode: boolean): string | null {
  try {
    const html = katex.renderToString(tex, {
      throwOnError: true,
      displayMode,
      trust: false, // LLM-текст недоверенный — не пускаем \href/\includegraphics и т.п.
      strict: "ignore",
    })
    return DOMPurify.sanitize(html) // второй слой защиты поверх trust:false
  } catch {
    return null
  }
}

// html — из katex.renderToString (trust:false) + DOMPurify.sanitize (двойной слой).
function InlineMath({ tex }: { tex: string }) {
  const html = tryKatex(tex, false)
  if (html == null) return <>{`$${tex}$`}</>
  return <span dangerouslySetInnerHTML={{ __html: html }} />
}

function MathBlock({ tex }: { tex: string }) {
  const html = tryKatex(tex, true)
  if (html == null) return <CodeBlock lang="" code={tex} />
  return <div className="overflow-x-auto py-1" dangerouslySetInnerHTML={{ __html: html }} />
}

// ---------- Код / Mermaid ----------

function CodeBlock({ lang, code }: { lang: string; code: string }) {
  return (
    <div className="overflow-x-auto rounded-lg border bg-muted p-3">
      {lang && (
        <p className="mb-1.5 text-xs font-medium uppercase tracking-wider text-muted-foreground">
          {lang}
        </p>
      )}
      <pre className="text-xs leading-relaxed text-foreground">
        <code>{code}</code>
      </pre>
    </div>
  )
}

// Ставим mermaid.initialize один раз на всё приложение (не на каждую диаграмму).
let mermaidInitialized = false

// Диаграмма рендерится асинхронно (динамический импорт — mermaid тяжёлый, не тянем его в общий
// бандл ради пары чатов). Невалидный синтаксис (LLM регулярно ошибается, см. JS-13) → тихий откат
// на обычный код-блок, никогда не показываем сломанный/пустой рендер молча.
function MermaidBlock({ code }: { code: string }) {
  const rawId = useId().replace(/[^a-zA-Z0-9]/g, "")
  const [state, setState] = useState<{ svg: string } | { failed: true } | null>(null)

  useEffect(() => {
    let cancelled = false
    async function run() {
      try {
        const { default: mermaid } = await import("mermaid")
        if (!mermaidInitialized) {
          mermaid.initialize({
            startOnLoad: false,
            securityLevel: "strict",
            theme: "neutral",
            fontFamily: "inherit",
          })
          mermaidInitialized = true
        }
        await mermaid.parse(code)
        const { svg } = await mermaid.render(`mmd-${rawId}`, code)
        if (!cancelled) setState({ svg: DOMPurify.sanitize(svg) }) // второй слой поверх securityLevel:"strict"
      } catch {
        if (!cancelled) setState({ failed: true })
      }
    }
    void run()
    return () => {
      cancelled = true
    }
  }, [code, rawId])

  if (state == null) return <Skeleton className="h-24" />
  if ("failed" in state) return <CodeBlock lang="mermaid" code={code} />
  // svg — из mermaid.render (securityLevel:"strict") + DOMPurify.sanitize (двойной слой).
  return (
    <div
      className="overflow-x-auto rounded-lg border bg-card p-3 [&_svg]:mx-auto"
      dangerouslySetInnerHTML={{ __html: state.svg }}
    />
  )
}

// ---------- Инлайн-разметка ----------

// `код` → <code>, **жирный** → <strong>, *курсив* → <em>, [текст](https://…) → ссылка,
// ==хайлайт== → <mark> (приглушённый акцент для легенды), $формула$ → KaTeX, голые URL —
// ссылки. Формула — без пробела у границ ($x$, не $ x $), иначе цепляем случайные
// "$150k ... $200k" (валюта в резюме/вакансиях) как обрывок формулы. Курсив только через
// `*`: `_` встречается в именах инструментов (read_work_terms) и ломал бы их.
const INLINE_RE =
  /(`[^`\n]+`|\*\*[^*]+\*\*|\[[^\]\n]+\]\(https?:\/\/[^\s)]+\)|\*(?![\s*])[^*\n]+?(?<![\s*])\*|==[^=]+==|\$(?!\s)[^$\n]+?(?<!\s)\$)/g
const LINK_RE = /^\[([^\]\n]+)\]\((https?:\/\/[^\s)]+)\)$/

const LINK_CLS =
  "font-medium text-sky-700 underline decoration-sky-300 underline-offset-2 hover:text-sky-800"

function renderPlain(text: string, key: number): ReactNode {
  if (!/https?:\/\//.test(text)) return <Fragment key={key}>{text}</Fragment>
  return (
    <Fragment key={key}>
      {text.split(/(https?:\/\/[^\s<)]+)/g).map((part, j) =>
        /^https?:\/\//.test(part) ? (
          <a key={j} href={part} target="_blank" rel="noopener noreferrer" className={LINK_CLS}>
            {part}
          </a>
        ) : (
          <Fragment key={j}>{part}</Fragment>
        ),
      )}
    </Fragment>
  )
}

function renderInline(text: string): ReactNode {
  const parts = text.split(INLINE_RE)
  return parts.map((part, i) => {
    if (!part) return null
    if (part.length > 2 && part.startsWith("`") && part.endsWith("`")) {
      return (
        <code key={i} className="rounded bg-muted px-1 py-0.5 font-mono text-foreground">
          {part.slice(1, -1)}
        </code>
      )
    }
    if (part.length > 4 && part.startsWith("**") && part.endsWith("**")) {
      return (
        <strong key={i} className="font-semibold text-foreground">
          {part.slice(2, -2)}
        </strong>
      )
    }
    const link = LINK_RE.exec(part)
    if (link) {
      return (
        <a key={i} href={link[2]} target="_blank" rel="noopener noreferrer" className={LINK_CLS}>
          {link[1]}
        </a>
      )
    }
    if (part.length > 2 && part.startsWith("*") && part.endsWith("*")) {
      return <em key={i}>{part.slice(1, -1)}</em>
    }
    if (part.startsWith("==") && part.endsWith("==") && part.length > 4) {
      return (
        <mark key={i} className="rounded bg-amber-100/70 px-1 font-medium text-foreground">
          {part.slice(2, -2)}
        </mark>
      )
    }
    if (part.startsWith("$") && part.endsWith("$") && part.length > 2) {
      return <InlineMath key={i} tex={part.slice(1, -1)} />
    }
    return renderPlain(part, i)
  })
}

type ListItem = { text: string; depth: number }

type Block =
  | { kind: "h1" | "h2" | "h3" | "h4" | "p" | "quote"; text: string }
  | { kind: "ul" | "ol"; items: ListItem[] }
  | { kind: "table"; head: string[]; rows: string[][] }
  | { kind: "hr" }
  | { kind: "code"; lang: string; code: string }
  | { kind: "mathblock"; tex: string }

function splitRow(line: string): string[] {
  const inner = line.trim().replace(/^\|/, "").replace(/\|$/, "")
  return inner.split("|").map((c) => c.trim())
}

const TABLE_SEP_RE = /^\s*\|?\s*:?-{2,}:?\s*(\|\s*:?-{2,}:?\s*)*\|?\s*$/

// Группируем строки в блоки: подряд идущие пункты списка → один <ul>/<ol>, строки таблицы
// (`| a | b |` + разделитель `|---|`) → одна таблица, подряд идущие `> ` → одна цитата.
function parseTextBlocks(md: string): Block[] {
  const blocks: Block[] = []
  let list: { kind: "ul" | "ol"; items: ListItem[] } | null = null

  const flush = () => {
    if (list) {
      blocks.push(list)
      list = null
    }
  }

  const lines = md.split("\n")
  for (let idx = 0; idx < lines.length; idx++) {
    const line = lines[idx].trimEnd()
    const bullet = /^(\s*)[-*•]\s+(.*)$/.exec(line)
    const ordered = /^(\s*)\d+[.)]\s+(.*)$/.exec(line)

    if (bullet && !/^\s*([-*])\s*\1\s*\1[\s\-*]*$/.test(line)) {
      const depth = Math.min(2, Math.floor(bullet[1].length / 2))
      if (list?.kind !== "ul" && !(list && depth > 0)) {
        flush()
        list = { kind: "ul", items: [] }
      }
      list!.items.push({ text: bullet[2], depth })
      continue
    }
    if (ordered) {
      const depth = Math.min(2, Math.floor(ordered[1].length / 2))
      if (list?.kind !== "ol" && !(list && depth > 0)) {
        flush()
        list = { kind: "ol", items: [] }
      }
      list!.items.push({ text: ordered[2], depth })
      continue
    }

    flush()
    if (!line.trim()) continue

    // Таблица: строка с `|` и следом строка-разделитель.
    if (line.includes("|") && idx + 1 < lines.length && TABLE_SEP_RE.test(lines[idx + 1])) {
      const head = splitRow(line)
      const rows: string[][] = []
      idx += 2
      while (idx < lines.length && lines[idx].includes("|") && lines[idx].trim()) {
        rows.push(splitRow(lines[idx]))
        idx++
      }
      idx--
      blocks.push({ kind: "table", head, rows })
      continue
    }
    if (/^\s*([-*_])\s*\1\s*\1[\s\-*_]*$/.test(line)) {
      blocks.push({ kind: "hr" })
      continue
    }
    if (line.startsWith(">")) {
      const text = line.replace(/^>\s?/, "")
      const prev = blocks[blocks.length - 1]
      if (prev?.kind === "quote") prev.text += `\n${text}`
      else blocks.push({ kind: "quote", text })
      continue
    }
    if (line.startsWith("#### ")) blocks.push({ kind: "h4", text: line.slice(5) })
    else if (line.startsWith("### ")) blocks.push({ kind: "h3", text: line.slice(4) })
    else if (line.startsWith("## ")) blocks.push({ kind: "h2", text: line.slice(3) })
    else if (line.startsWith("# ")) blocks.push({ kind: "h1", text: line.slice(2) })
    else blocks.push({ kind: "p", text: line })
  }
  flush()
  return blocks
}

// Код-фенсы (```lang\n...\n```) и блочные формулы ($$...$$) режем ДО построчного парсера — это
// многострочные конструкции, которые тот не понимает. Всё, что между ними — обычный markdown.
const FENCE_RE = /```(\w+)?\r?\n([\s\S]*?)```|\$\$([\s\S]*?)\$\$/g

function buildBlocks(md: string): Block[] {
  const blocks: Block[] = []
  let last = 0
  for (const m of md.matchAll(FENCE_RE)) {
    const idx = m.index ?? 0
    if (idx > last) blocks.push(...parseTextBlocks(md.slice(last, idx)))
    if (m[2] !== undefined) {
      blocks.push({ kind: "code", lang: (m[1] ?? "").toLowerCase(), code: m[2].replace(/\n$/, "") })
    } else if (m[3] !== undefined) {
      blocks.push({ kind: "mathblock", tex: m[3].trim() })
    }
    last = idx + m[0].length
  }
  if (last < md.length) blocks.push(...parseTextBlocks(md.slice(last)))
  return blocks
}

// `chat`: вариант под пузыри чата (крупнее, чёрный текст) вместо приглушённого текста вкладок.
export function MarkdownView({ markdown, chat = false }: { markdown: string; chat?: boolean }) {
  const blocks = useMemo(() => buildBlocks(markdown), [markdown])
  const pCls = chat
    ? "text-base leading-snug text-foreground"
    : "text-sm leading-relaxed text-muted-foreground"
  const liBase = chat ? "text-base leading-snug text-foreground" : "text-sm text-muted-foreground"

  return (
    <div className="space-y-3">
      {blocks.map((b, i) => {
        if (b.kind === "h1")
          return (
            <h1 key={i} className="text-xl font-semibold text-foreground">
              {renderInline(b.text)}
            </h1>
          )
        if (b.kind === "h2")
          return (
            <h2 key={i} className="mt-6 text-base font-semibold text-foreground">
              {renderInline(b.text)}
            </h2>
          )
        if (b.kind === "h3")
          return (
            <h3 key={i} className="mt-4 text-sm font-semibold text-foreground">
              {renderInline(b.text)}
            </h3>
          )
        if (b.kind === "h4")
          return (
            <h4 key={i} className="mt-3 text-sm font-semibold text-foreground">
              {renderInline(b.text)}
            </h4>
          )
        if (b.kind === "ul" || b.kind === "ol") {
          const cls = `${b.kind === "ul" ? "list-disc" : "list-decimal"} space-y-1 pl-5 ${liBase}`
          const items = b.items.map((it, j) => (
            <li key={j} className={it.depth === 1 ? "ml-5" : it.depth === 2 ? "ml-10" : undefined}>
              {renderInline(it.text)}
            </li>
          ))
          return b.kind === "ul" ? (
            <ul key={i} className={cls}>
              {items}
            </ul>
          ) : (
            <ol key={i} className={cls}>
              {items}
            </ol>
          )
        }
        if (b.kind === "table")
          return (
            <div key={i} className="overflow-x-auto rounded-lg border border-border">
              <table className="w-full border-collapse text-sm">
                <thead className="bg-muted">
                  <tr>
                    {b.head.map((cell, j) => (
                      <th
                        key={j}
                        className="border-b border-border px-3 py-2 text-left font-semibold text-foreground"
                      >
                        {renderInline(cell)}
                      </th>
                    ))}
                  </tr>
                </thead>
                <tbody>
                  {b.rows.map((row, r) => (
                    <tr key={r} className="border-b border-border last:border-b-0">
                      {b.head.map((_, j) => (
                        <td key={j} className="px-3 py-2 align-top text-foreground">
                          {renderInline(row[j] ?? "")}
                        </td>
                      ))}
                    </tr>
                  ))}
                </tbody>
              </table>
            </div>
          )
        if (b.kind === "hr") return <hr key={i} className="border-border" />
        if (b.kind === "quote")
          return (
            <blockquote
              key={i}
              className={`whitespace-pre-line border-l-2 border-border pl-3 ${chat ? "text-base" : "text-sm"} text-muted-foreground`}
            >
              {renderInline(b.text)}
            </blockquote>
          )
        if (b.kind === "code")
          return b.lang === "mermaid" ? (
            <MermaidBlock key={i} code={b.code} />
          ) : (
            <CodeBlock key={i} lang={b.lang} code={b.code} />
          )
        if (b.kind === "mathblock") return <MathBlock key={i} tex={b.tex} />
        return (
          <p key={i} className={pCls}>
            {renderInline("text" in b ? b.text : "")}
          </p>
        )
      })}
    </div>
  )
}
