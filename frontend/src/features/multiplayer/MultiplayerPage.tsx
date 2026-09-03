import { useEffect, useRef, useState } from "react"
import { Link } from "react-router-dom"
import { HowToPlay } from "@/features/multiplayer/wolves/HowToPlay"
import { WolvesLobby } from "@/features/multiplayer/wolves/WolvesLobby"
import { useViewportHeight, syncViewportUnits } from "@/lib/use-viewport-height"
import { setImmersive } from "./immersive"
import "./gfx/shell/tokens.css"

/**
 * Хаб раздела «Мультиплеер»: сейчас одна игра — «Хрюши и Волки».
 *
 * Пока открыт живой стол (`atTable`), шапка с описанием и «Как играть» прячется, рельс
 * сворачивается, а раздел перестаёт скроллиться целиком — стол сам держит свою высоту и
 * скроллит длинный текст внутри блоков (иммерсивный режим). `WolvesLobby` при этом не
 * перемонтируется — он владелец состояния «за столом», ветвление только вокруг него.
 *
 * Э35.7: вся разметка выражена через видимую высоту экрана (`--mp-vh` пишется из JS с
 * учётом виртуальной клавиатуры через visualViewport). Ни лобби, ни игровой стол
 * не должны заставлять пользователя скроллить раздел — текст «Как играть» и колода
 * реплик ужимаются через cqh-токены внутри game-stage, а описание и «Как играть»
 * в лобби занимают то, что осталось от шапки стола.
 */
export function MultiplayerPage() {
  const [atTable, setAtTable] = useState(false)
  const rootRef = useRef<HTMLDivElement>(null)
  const vh = useViewportHeight()

  useEffect(() => {
    setImmersive(atTable)
  }, [atTable])

  useEffect(() => () => setImmersive(false), [])

  useEffect(() => {
    syncViewportUnits(rootRef.current, vh)
  }, [vh])

  return (
    <div
      ref={rootRef}
      className="mp-root mp-skin-booth flex min-h-0 min-w-0 flex-1 flex-col overflow-hidden"
      style={{ maxHeight: "var(--mp-vh)" }}
    >
      <div
        id="screen-start-multiplayer"
        className={
          atTable
            ? "flex min-h-0 min-w-0 flex-1 flex-col overflow-hidden"
            : "flex min-h-0 min-w-0 flex-1 flex-col gap-3 overflow-hidden px-6 pb-3 pt-4"
        }
      >
        {!atTable ? (
          <header className="mp-lobby-head shrink-0 space-y-1">
            <h1 className="mp-display text-base font-medium text-slate-900">Хрюши и Волки</h1>
            <p className="max-w-3xl text-sm leading-relaxed text-slate-600">
              Попробуй победить ИИ-хрюшу: лови волков в кабинете найма, штампуй бумаги, блефуй
              картами.
            </p>
          </header>
        ) : null}

        <div
          className={
            atTable
              ? "flex min-h-0 min-w-0 flex-1 flex-col overflow-hidden"
              : "flex min-h-0 min-w-0 flex-1 flex-col gap-3 lg:flex-row"
          }
        >
          {!atTable ? (
            <aside className="mp-lobby-howto min-h-0 shrink-0 overflow-y-auto overscroll-contain lg:w-72 lg:flex-shrink-0">
              <HowToPlay />
            </aside>
          ) : null}
          <div
            className={
              atTable
                ? "flex min-h-0 min-w-0 flex-1 flex-col"
                : "min-h-0 min-w-0 flex-1 overflow-y-auto overscroll-contain"
            }
          >
            <WolvesLobby onTableChange={setAtTable} />
            {!atTable && import.meta.env.DEV ? (
              <p className="pt-3 text-xs text-slate-500">
                <Link
                  to="/multiplayer/dev/gfx"
                  className="underline underline-offset-2 hover:text-slate-800"
                >
                  DEV: витрина примитивов gfx
                </Link>
              </p>
            ) : null}
          </div>
        </div>
      </div>
    </div>
  )
}
