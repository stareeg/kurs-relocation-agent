export type SparklinePoint = {
  /** Optional x (day ordinal / index). Defaults to array index. */
  x?: number
  y: number
}

export function normalizePoints(
  points: readonly SparklinePoint[] | readonly number[],
): { x: number; y: number }[] {
  if (points.length === 0) return []
  if (typeof points[0] === "number") {
    return (points as readonly number[]).map((y, i) => ({ x: i, y }))
  }
  return (points as readonly SparklinePoint[]).map((p, i) => ({
    x: p.x ?? i,
    y: p.y,
  }))
}

/** empty → nothing; one point → dot; 2+ → polyline (W-12 geometry contract). */
export function sparklineKind(
  points: readonly SparklinePoint[] | readonly number[],
): "empty" | "point" | "line" {
  const n = normalizePoints(points).length
  if (n === 0) return "empty"
  if (n === 1) return "point"
  return "line"
}

export type SparklineCoord = { cx: number; cy: number }

/**
 * Пиксельные координаты нормализованных точек внутри `width`×`height` (V-07: та же раскладка
 * нужна и для отрисовки линии, и для поиска ближайшей точки под визиром — общая геометрия не
 * даёт им разойтись).
 */
export function sparklineLayout(
  normalized: readonly { x: number; y: number }[],
  width: number,
  height: number,
  pad = 1,
): { coords: SparklineCoord[] } {
  if (normalized.length === 0) return { coords: [] }

  const xs = normalized.map((p) => p.x)
  const ys = normalized.map((p) => p.y)
  const minX = Math.min(...xs)
  const maxX = Math.max(...xs)
  const minY = Math.min(...ys)
  const maxY = Math.max(...ys)
  const spanX = maxX - minX || 1
  const spanY = maxY - minY || 1
  const innerW = width - pad * 2
  const innerH = height - pad * 2

  const coords = normalized.map((p) => ({
    cx: pad + ((p.x - minX) / spanX) * innerW,
    cy: pad + innerH - ((p.y - minY) / spanY) * innerH,
  }))

  return { coords }
}
