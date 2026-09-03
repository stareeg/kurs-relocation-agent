// Чистые функции ветки вложения (план §3, Э4-3) — без React, отдельно от RouteBadge.tsx,
// чтобы компонент экспортировал только компонент (react-refresh/only-export-components).

import type { AttachmentAnalysis, AttachmentRoute } from "@/api/attachments"

const LOW_CONFIDENCE = 0.6

/** Дефолт ветки — тот же, что и на бэке (`resolve_attachment_route` без override). */
export function defaultAttachmentRoute(
  analysis: AttachmentAnalysis | null | undefined,
): AttachmentRoute {
  return analysis?.kind === "correspondence" ? "correspondence" : "material"
}

/** <0.6 — классификатор не уверен в kind: ярлык раскрывается по умолчанию (§4.2 плана). */
export function isLowConfidenceRoute(analysis: AttachmentAnalysis | null | undefined): boolean {
  return (analysis?.confidence ?? 1) < LOW_CONFIDENCE
}
