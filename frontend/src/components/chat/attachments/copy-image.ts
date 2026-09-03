// «Копировать картинку» из контекстного меню сообщения (план §6.6). Буфер обмена браузеров
// надёжно принимает только image/png — WebP-оригинал (см. `core/platform/images`) конвертируется
// на лету через canvas перед записью в clipboard.

export function isPngMime(mime: string): boolean {
  return mime === "image/png"
}

async function fetchImageBlob(url: string): Promise<Blob> {
  const res = await fetch(url, { credentials: "include" })
  if (!res.ok) throw new Error(`Не удалось загрузить картинку (${res.status})`)
  return res.blob()
}

function blobToPng(blob: Blob): Promise<Blob> {
  return new Promise((resolve, reject) => {
    const img = new Image()
    const objectUrl = URL.createObjectURL(blob)
    const cleanup = () => URL.revokeObjectURL(objectUrl)
    img.onload = () => {
      const canvas = document.createElement("canvas")
      canvas.width = img.naturalWidth
      canvas.height = img.naturalHeight
      const ctx = canvas.getContext("2d")
      if (!ctx) {
        cleanup()
        reject(new Error("canvas 2d недоступен"))
        return
      }
      ctx.drawImage(img, 0, 0)
      canvas.toBlob((pngBlob) => {
        cleanup()
        if (pngBlob) resolve(pngBlob)
        else reject(new Error("не удалось собрать PNG"))
      }, "image/png")
    }
    img.onerror = () => {
      cleanup()
      reject(new Error("не удалось загрузить картинку"))
    }
    img.src = objectUrl
  })
}

/** Приводит произвольный blob картинки к PNG — оригинал остаётся как есть, если уже PNG. */
export async function toPngBlob(blob: Blob): Promise<Blob> {
  return isPngMime(blob.type) ? blob : blobToPng(blob)
}

/** Скачивает картинку по `url` (тот же origin — dev-прокси/cookie) и кладёт PNG в буфер обмена.
 *
 * Safari требует, чтобы `clipboard.write` вызывался синхронно в жесте пользователя.
 * Поэтому в ClipboardItem кладём Promise, а не уже готовый Blob после await fetch.
 */
export async function copyImageToClipboard(url: string): Promise<void> {
  if (!navigator.clipboard?.write || typeof ClipboardItem === "undefined") {
    throw new Error("Буфер обмена недоступен в этом браузере")
  }
  const pngPromise = fetchImageBlob(url).then((blob) => toPngBlob(blob))
  await navigator.clipboard.write([new ClipboardItem({ "image/png": pngPromise })])
}
