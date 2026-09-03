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

// **жирный** → <strong>, ==хайлайт== → <mark> (приглушённый акцент для легенды), $формула$ →
// KaTeX. Формула — без пробела у границ ($x$, не $ x $), иначе цепляем случайные "$150k ... $200k"
// (валюта в резюме/вакансиях) как обрывок формулы.
function renderInline(text: string): ReactNode {
  const parts = text.split(/(\*\*[^*]+\*\*|==[^=]+==|\$(?!\s)[^$\n]+?(?<!\s)\$)/g)
  return parts.map((part, i) => {
    if (part.startsWith("**") && part.endsWith("**")) {
      return (
        <strong key={i} className="font-semibold text-foreground">
          {part.slice(2, -2)}
        </strong>
      )
    }
    if (part.startsWith("==") && part.endsWith("==")) {
      return (
        <mark key={i} className="rounded bg-amber-100/70 px-1 font-medium text-foreground">
          {part.slice(2, -2)}
        </mark>
      )
    }
    if (part.startsWith("$") && part.endsWith("$") && part.length > 2) {
      return <InlineMath key={i} tex={part.slice(1, -1)} />
    }
    return <Fragment key={i}>{part}</Fragment>
  })
}

type Block =
  | { kind: "h1" | "h2" | "h3" | "p"; text: string }
  | { kind: "ul" | "ol"; items: string[] }
  | { kind: "code"; lang: string; code: string }
  | { kind: "mathblock"; tex: string }

// Группируем строки в блоки: подряд идущие пункты списка → один <ul>/<ol>.
function parseTextBlocks(md: string): Block[] {
  const blocks: Block[] = []
  let list: { kind: "ul" | "ol"; items: string[] } | null = null

  const flush = () => {
    if (list) {
      blocks.push(list)
      list = null
    }
  }

  for (const raw of md.split("\n")) {
    const line = raw.trimEnd()
    const bullet = /^[-*]\s+(.*)$/.exec(line)
    const ordered = /^\d+\.\s+(.*)$/.exec(line)

    if (bullet) {
      if (list?.kind !== "ul") {
        flush()
        list = { kind: "ul", items: [] }
      }
      list.items.push(bullet[1])
      continue
    }
    if (ordered) {
      if (list?.kind !== "ol") {
        flush()
        list = { kind: "ol", items: [] }
      }
      list.items.push(ordered[1])
      continue
    }

    flush()
    if (!line.trim()) continue
    if (line.startsWith("### ")) blocks.push({ kind: "h3", text: line.slice(4) })
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
        if (b.kind === "ul" || b.kind === "ol") {
          const cls = `${b.kind === "ul" ? "list-disc" : "list-decimal"} space-y-1 pl-5 ${liBase}`
          const items = b.items.map((it, j) => <li key={j}>{renderInline(it)}</li>)
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
        if (b.kind === "code")
          return b.lang === "mermaid" ? (
            <MermaidBlock key={i} code={b.code} />
          ) : (
            <CodeBlock key={i} lang={b.lang} code={b.code} />
          )
        if (b.kind === "mathblock") return <MathBlock key={i} tex={b.tex} />
        return (
          <p key={i} className={pCls}>
            {renderInline(b.kind === "p" ? b.text : "")}
          </p>
        )
      })}
    </div>
  )
}
