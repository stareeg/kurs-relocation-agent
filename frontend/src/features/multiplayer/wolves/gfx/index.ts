/**
 * Графика «Хрюш и Волков»: кабинет, штампы, бумаги, фишки, шкала фаз.
 *
 * Всё здесь говорит словарём этой игры (фазы, роли, теги колоды, «волк/человек»), поэтому
 * второй игре не переиспользуется — она рисует свою сцену с нуля. Общие примитивы раздела —
 * в `gfx/shell/` (см. Э17.5: общую библиотеку игровых UI-компонентов не строим).
 */

export { BoothFrame } from "./BoothFrame"
export { CardBack, CardFace, FlippableCard, type ExperienceTag } from "./CardFace"
export { EnergyPips } from "./EnergyPips"
export { PhaseCountdown } from "./PhaseCountdown"
export { InkHighlight } from "./InkHighlight"
export { PhaseRail, phaseCaptionLabel, type PhaseId } from "./PhaseRail"
export { RoleChip, type RoleStatus } from "./RoleChip"
export { RuleBulletin, type BulletinGate } from "./RuleBulletin"
export { SeatToken } from "./SeatToken"
export { StampButton, type StampKind } from "./StampButton"
export { useStampImprints } from "./useStampImprints"
