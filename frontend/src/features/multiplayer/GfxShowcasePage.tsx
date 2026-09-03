import { useEffect, useState } from "react"
import { Link, Navigate } from "react-router-dom"
import { PaperSheet, RoomCard, TableFelt, TickerTape } from "./gfx/shell"
import {
  BoothFrame,
  EnergyPips,
  FlippableCard,
  InkHighlight,
  PhaseRail,
  RoleChip,
  RuleBulletin,
  SeatToken,
  StampButton,
  useStampImprints,
} from "./wolves/gfx"

/**
 * DEV-витрина примитивов gfx (Э2). В production роут не монтируется.
 * Кликабельно: штамп оставляет след, карта переворачивается, маркеры улик.
 */
export function GfxShowcasePage() {
  if (!import.meta.env.DEV) {
    return <Navigate to="/multiplayer" replace />
  }

  return <GfxShowcaseBody />
}

function GfxShowcaseBody() {
  const { addImprint, clear, overlay } = useStampImprints()
  const [marks, setMarks] = useState<string[]>([])
  const [seconds, setSeconds] = useState(28)
  const [energy, setEnergy] = useState(4)

  useEffect(() => {
    const id = window.setInterval(() => {
      setSeconds((s) => (s <= 0 ? 28 : s - 1))
    }, 1000)
    return () => window.clearInterval(id)
  }, [])

  const toggleMark = (id: string) => {
    setMarks((prev) => {
      if (prev.includes(id)) return prev.filter((x) => x !== id)
      if (prev.length >= 2) return [prev[1]!, id]
      return [...prev, id]
    })
  }

  return (
    <div className="mp-root mp-skin-booth flex min-h-0 min-w-0 flex-1 flex-col overflow-x-hidden">
      <div className="min-w-0 flex-1 overflow-y-auto overscroll-contain">
        <div className="space-y-6 px-6 pb-10 pt-6">
          <div className="flex flex-wrap items-end justify-between gap-3">
            <div className="space-y-1">
              <p className="mp-mono text-[10px] uppercase tracking-wider text-slate-500">
                DEV · /multiplayer/dev/gfx
              </p>
              <h1 className="mp-display text-xl font-semibold text-slate-900">
                Примитивы кабинета
              </h1>
              <p className="max-w-xl text-sm text-slate-600">
                Штамп оставляет отпечаток, карта переворачивается, улик можно отметить две.
                Не продуктовый экран — только сверка арт-языка перед Э3/Э6.
              </p>
            </div>
            <Link
              to="/multiplayer"
              className="mp-mono text-xs text-slate-500 underline-offset-2 hover:underline"
            >
              ← к хабу
            </Link>
          </div>

          <PhaseRail current="inspect" secondsLeft={seconds} slotLabel="Слот 2/5" />

          <div className="grid gap-4 lg:grid-cols-2">
            <BoothFrame
              footer={
                <div className="flex flex-wrap items-center gap-2">
                  <StampButton kind="approve" onStamp={addImprint} />
                  <StampButton kind="reject" onStamp={addImprint} />
                  <StampButton kind="probe" onStamp={addImprint} />
                  <StampButton kind="offer" onStamp={addImprint} />
                  <button
                    type="button"
                    onClick={clear}
                    className="mp-mono ml-auto text-[10px] text-slate-500 underline-offset-2 hover:underline"
                  >
                    стереть отпечатки
                  </button>
                </div>
              }
            >
              <div className="flex flex-wrap items-center justify-between gap-2">
                <EnergyPips value={energy} />
                <button
                  type="button"
                  className="mp-mono text-[10px] text-slate-600 underline-offset-2 hover:underline"
                  onClick={() => setEnergy((e) => (e <= 0 ? 5 : e - 1))}
                >
                  −1 энергия
                </button>
              </div>
              <RuleBulletin
                dayLabel="день найма"
                gates={[
                  { id: "g1", label: "Knockout: только Москва / гибрид" },
                  { id: "g2", label: "Стек без «1С» — в архив без хрюши" },
                  { id: "g3", label: "Офферный штамп закрыт: бюджет заморожен" },
                ]}
              />
              <PaperSheet title="Резюме · кандидат #3" overlay={overlay}>
                <p className="mb-2 text-xs opacity-70">Ткни две улики:</p>
                <p>
                  Опыт:{" "}
                  <InkHighlight
                    selected={marks.includes("dates")}
                    onToggle={() => toggleMark("dates")}
                  >
                    2022–2024 тимлид 40 человек
                  </InkHighlight>
                  , стек{" "}
                  <InkHighlight
                    selected={marks.includes("stack")}
                    onToggle={() => toggleMark("stack")}
                  >
                    Vue + немного React
                  </InkHighlight>
                  . Акт ИП на{" "}
                  <InkHighlight
                    selected={marks.includes("ip")}
                    onToggle={() => toggleMark("ip")}
                  >
                    Иванова К.
                  </InkHighlight>
                  .
                </p>
              </PaperSheet>
            </BoothFrame>

            <div className="space-y-3">
              <TableFelt>
                <div className="mb-4 flex justify-around">
                  <SeatToken label="Аня" accent="hr" />
                  <SeatToken label="Волк?" accent="wolf" revealed="wolf" />
                  <SeatToken label="Кир" revealed="human" />
                  <div className="flex flex-col items-center gap-1">
                    <SeatToken label="Зритель" />
                    <RoleChip status="spectator" />
                  </div>
                </div>
                <div className="flex flex-wrap justify-center gap-3">
                  <FlippableCard
                    tag="bluff"
                    title="Тащил прод в соло, тимлид был в отпуске"
                  />
                  <FlippableCard
                    tag="incident"
                    title="Роняли в пятницу — поднял до понедельника"
                    startFaceUp
                  />
                  <FlippableCard tag="batna" title="У меня другой оффер до пятницы" />
                </div>
                <div className="mt-4 flex flex-wrap gap-2">
                  <RoleChip status="waiting" />
                  <RoleChip status="interview" />
                  <RoleChip status="rejected" />
                  <RoleChip status="offer" />
                </div>
              </TableFelt>

              <TickerTape text="Тишина после скрина. Бюджет якобы есть." />
              <p className="mp-mono text-[10px] text-slate-500">
                Моушн Э13: штамп slam + imprint, deal карт, ticker enter/scan.
              </p>

              <div className="space-y-2">
                <p className="mp-mono text-[10px] uppercase tracking-wider text-slate-500">
                  Лобби · RoomCard
                </p>
                <RoomCard
                  name="Вечерний отсев"
                  code="КРН7ВХ"
                  seatsFree={2}
                  seatsTotal={5}
                  phaseLabel="осмотр"
                />
                <RoomCard
                  name="Соло vs LLM"
                  code="ХРЮ001"
                  seatsFree={0}
                  seatsTotal={4}
                  phaseLabel="лобби"
                />
              </div>
            </div>
          </div>
        </div>
      </div>
    </div>
  )
}
