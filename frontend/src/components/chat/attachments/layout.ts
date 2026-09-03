// Чистые функции раскладки картинок в пузыре (план chat_image_attachments_2026_08_03.md, §6.3).
// Без React — размеры уже известны из БД (width/height), поэтому это чистая функция от чисел,
// а не измерение DOM; аспект резервируется через `aspect-ratio` на стороне компонента.

import type { AttachmentOut } from "@/api/attachments"

/**
 * Минимальная форма вложения, нужная виджетам ленты/просмотрщика. Алиас на `AttachmentOut` —
 * когда Э2-5 добавит `MessageAttachmentOut` в схему сообщений, он структурно совместим (то же
 * подмножество полей), поэтому виджеты не придётся переписывать.
 */
export type AttachmentLike = AttachmentOut

export type ImageCase = "normal" | "tiny" | "tall" | "wide"

const TINY_SIDE_PX = 96
const TALL_RATIO = 0.5
const WIDE_RATIO = 3

/** Классификация по табличным правилам плана: мелкая / обычная / длинная / широкая. */
export function classifyImage(width: number, height: number): ImageCase {
  if (width < TINY_SIDE_PX && height < TINY_SIDE_PX) return "tiny"
  const ratio = width / height
  if (ratio < TALL_RATIO) return "tall"
  if (ratio > WIDE_RATIO) return "wide"
  return "normal"
}

export interface SingleImageLayout {
  case: ImageCase
  /** Классы контейнера-обёртки (рамка/подложка мелкой картинки, обрезка длинной). */
  wrapClassName: string
  /** Классы самой `<img>`. */
  imgClassName: string
  objectPosition: "center" | "top" | "left"
  /** Кнопка «вся картинка» — только у длинного скрина, что сейчас не развёрнут. */
  showExpandButton: boolean
  /** Нижний градиент-затухание — только у обрезанного длинного скрина. */
  showFadeOverlay: boolean
}

const NORMAL_MAX_PX = 320
const TALL_EXPANDED_MAX_PX = 720

/**
 * Раскладка одной картинки. `expanded` — только для случая `tall`: развернуть до 720px в ленте
 * по клику «вся картинка» (план §6.3).
 */
export function singleImageLayout(
  width: number,
  height: number,
  opts: { expanded?: boolean } = {},
): SingleImageLayout {
  const kase = classifyImage(width, height)
  switch (kase) {
    case "tiny":
      return {
        case: kase,
        wrapClassName: "inline-block rounded-md border border-border bg-muted/40 p-1",
        imgClassName: "block",
        objectPosition: "center",
        showExpandButton: false,
        showFadeOverlay: false,
      }
    case "tall": {
      const expanded = opts.expanded ?? false
      return {
        case: kase,
        wrapClassName: expanded
          ? `relative max-w-[${NORMAL_MAX_PX}px] max-h-[${TALL_EXPANDED_MAX_PX}px] overflow-hidden`
          : `relative max-w-[${NORMAL_MAX_PX}px] max-h-[${NORMAL_MAX_PX}px] overflow-hidden`,
        imgClassName: "w-full object-cover object-top",
        objectPosition: "top",
        showExpandButton: !expanded,
        showFadeOverlay: !expanded,
      }
    }
    case "wide":
      return {
        case: kase,
        wrapClassName: `max-w-[${NORMAL_MAX_PX}px]`,
        imgClassName: "w-full object-contain object-left",
        objectPosition: "left",
        showExpandButton: false,
        showFadeOverlay: false,
      }
    default:
      return {
        case: kase,
        wrapClassName: `max-w-[min(${NORMAL_MAX_PX}px,100%)] max-h-[${NORMAL_MAX_PX}px]`,
        imgClassName: `max-h-[${NORMAL_MAX_PX}px] w-auto object-contain`,
        objectPosition: "center",
        showExpandButton: false,
        showFadeOverlay: false,
      }
  }
}

export interface GridLayout {
  /** Классы grid-контейнера. */
  containerClassName: string
  /** Классы на каждую видимую ячейку (длина = min(count, 4)). */
  cellClassNames: string[]
  /** Сколько картинок скрыто за последней ячейкой («+N» затемнение), 0 если не переполнено. */
  overflowCount: number
}

const MAX_VISIBLE_CELLS = 4

/** Сетка N картинок одного сообщения — правила из плана §6.3 (2/3/4/5+). */
export function attachmentGridLayout(count: number): GridLayout {
  if (count <= 1) {
    return {
      containerClassName: "grid grid-cols-1",
      cellClassNames: ["col-span-1"],
      overflowCount: 0,
    }
  }
  if (count === 2) {
    return {
      containerClassName: "grid grid-cols-2 gap-0.5",
      cellClassNames: ["", ""],
      overflowCount: 0,
    }
  }
  if (count === 3) {
    // Одна большая слева (растянута на обе строки) + две в столбик справа.
    return {
      containerClassName: "grid grid-cols-2 grid-rows-2 gap-0.5",
      cellClassNames: ["row-span-2", "", ""],
      overflowCount: 0,
    }
  }
  return {
    containerClassName: "grid grid-cols-2 grid-rows-2 gap-0.5",
    cellClassNames: ["", "", "", ""],
    overflowCount: count > MAX_VISIBLE_CELLS ? count - MAX_VISIBLE_CELLS : 0,
  }
}

/** Сколько ячеек сетки реально рендерится (остальные схлопнуты в «+N» последней). */
export function visibleAttachmentCount(count: number): number {
  return Math.min(count, MAX_VISIBLE_CELLS)
}
