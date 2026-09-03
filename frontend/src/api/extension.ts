import { apiFetchBlob } from "@/api/client"

export const EXTENSION_ZIP_FALLBACK_NAME = "career-copilot-extension.zip"

// triggerDownload копирует паттерн из api/logs.ts — два npm-модуля, общего lib для скачивания
// нет; при третьем таком месте стоит вынести в src/lib.
function triggerDownload(blob: Blob, filename: string): void {
  const anchor = document.createElement("a")
  anchor.href = URL.createObjectURL(blob)
  anchor.download = filename
  anchor.click()
  URL.revokeObjectURL(anchor.href)
}

/** EX-14: скачать собранное расширение zip'ом (страница «Расширение» больше не отдаёт
 * абсолютный путь на диске сервера — на захостенной VM он бессмыслен для пользователя).
 * Ошибки (409 «сборка не найдена», сеть) не проглатываем — страница показывает их текстом. */
export async function downloadExtensionZip(): Promise<void> {
  const { blob, filename } = await apiFetchBlob("/api/meta/extension/download")
  triggerDownload(blob, filename ?? EXTENSION_ZIP_FALLBACK_NAME)
}
