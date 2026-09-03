import { createContext, useContext } from "react"

// Глобальное «Свернуть все» / «Развернуть все» вкладки «Резюме» (F-?): каждая секция
// (`Section`) хранит свою свёрнутость в localStorage, а этот контекст отдаёт «сигнал» от
// кнопки под баллом резюме — по инкременту `signal` все секции форсированно сворачиваются
// (`collapse=true`) или разворачиваются (`collapse=false`).
export type ResumeCollapseState = {
  /** Счётчик команд; 0 = ничего не запускалось. */
  signal: number
  /** true — «Свернуть все», false — «Развернуть все». */
  collapse: boolean
  /** Поднять команду для всех секций (инкремент signal). */
  apply: (collapse: boolean) => void
}

export const ResumeCollapseContext = createContext<ResumeCollapseState>({
  signal: 0,
  collapse: false,
  apply: () => {},
})

export function useResumeCollapse(): ResumeCollapseState {
  return useContext(ResumeCollapseContext)
}
