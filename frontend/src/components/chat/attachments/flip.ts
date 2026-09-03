// FLIP-геометрия просмотрщика (план §6.4): открытие/закрытие анимируется из/в rect миниатюры,
// с которой кликнули. Чистая функция — WAAPI-вызов и замер `getBoundingClientRect()` остаются в
// ImageViewer.tsx, здесь только арифметика (тестируется без DOM/jsdom-анимаций).

export const FLIP_DURATION_MS = 240
export const FLIP_EASING = "cubic-bezier(.2,.8,.2,1)"

/** Пара WAAPI-кадров: transform, переводящий `to` в позицию/размер `from`, → `none`. */
export function flipKeyframes(from: DOMRect, to: DOMRect): Keyframe[] {
  const scaleX = to.width === 0 ? 1 : from.width / to.width
  const scaleY = to.height === 0 ? 1 : from.height / to.height
  const translateX = from.left + from.width / 2 - (to.left + to.width / 2)
  const translateY = from.top + from.height / 2 - (to.top + to.height / 2)
  return [
    { transform: `translate(${translateX}px, ${translateY}px) scale(${scaleX}, ${scaleY})` },
    { transform: "none" },
  ]
}
