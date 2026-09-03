/**
 * Примитивы раздела «Мультиплеер», не знающие, во что играют (Э17.8).
 *
 * Сюда попадает только то, что переживёт вторую игру без правок: у компонента не должно быть
 * в пропсах ни фаз, ни ролей, ни тегов колоды конкретной игры. Всё остальное — в
 * `wolves/gfx/`, даже если название звучит обобщённо: `PhaseRail` печатает ярлыки фаз Wolves,
 * `CardFace` — теги её колоды, `SeatToken` — «волк/человек». Разложить их сюда значило бы
 * завести границу, которая врёт.
 */

export { PaperSheet } from "./PaperSheet"
export { RoomCard } from "./RoomCard"
export { SlotStrip } from "./SlotStrip"
export { TableFelt } from "./TableFelt"
export { TickerTape } from "./TickerTape"

import "./tokens.css"
