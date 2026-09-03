import { CareerDelta } from "./CareerDelta"
import { CareerSnapshotStrip } from "./CareerSnapshotStrip"
import { FactsMemory } from "./FactsMemory"
import { TimelineFeed } from "./TimelineFeed"

/**
 * «Карьера» (Э9.8): один вертикальный поток без вкладок — снимок → что изменилось → лента →
 * память. Вкладка «Релокация» удалена (владелец подтвердил, план §8 вопрос 5), «Цели» была
 * мёртвым кодом и не подключалась нигде. «Достижения» (была отдельной секцией) переехала внутрь
 * «Памяти» колонкой рядом с «Пробелами» (правка владельца 2026-08-26).
 */
export function CareerPage() {
  return (
    <div className="flex min-h-0 min-w-0 flex-1 flex-col overflow-x-hidden">
      <div
        id="screen-start-career"
        className="min-w-0 flex-1 overflow-y-auto overflow-x-hidden overscroll-contain"
      >
        <div className="px-6 pb-6 pt-6 space-y-6">
          <CareerSnapshotStrip />
          <CareerDelta />
          <TimelineFeed />
          <FactsMemory />
        </div>
      </div>
    </div>
  )
}
