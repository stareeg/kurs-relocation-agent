// Клиентское сжатие картинки перед загрузкой (UX6-13, аватар): выбранный файл может быть
// несколько МБ прямо с телефона — даунскейл + перекодирование на канвасе в JPEG до отправки на
// бэкенд, который потом всё равно ещё раз нормализует байты сам (core.platform.images), но не
// должен получать по сети то, что заведомо большего размера, чем нужно маленькой круглой иконке.

const DEFAULT_MAX_SIDE_PX = 512
const DEFAULT_QUALITY = 0.85

function loadImage(file: File): Promise<HTMLImageElement> {
  return new Promise((resolve, reject) => {
    const img = new Image()
    const objectUrl = URL.createObjectURL(file)
    img.onload = () => {
      URL.revokeObjectURL(objectUrl)
      resolve(img)
    }
    img.onerror = () => {
      URL.revokeObjectURL(objectUrl)
      reject(new Error("Не удалось прочитать картинку"))
    }
    img.src = objectUrl
  })
}

/** Даунскейл до `maxSide` по длинной стороне (браузер сглаживает сам при drawImage) + JPEG. */
export async function compressImageFile(
  file: File,
  { maxSide = DEFAULT_MAX_SIDE_PX, quality = DEFAULT_QUALITY } = {},
): Promise<Blob> {
  const img = await loadImage(file)
  const scale = Math.min(1, maxSide / Math.max(img.naturalWidth, img.naturalHeight))
  const width = Math.max(1, Math.round(img.naturalWidth * scale))
  const height = Math.max(1, Math.round(img.naturalHeight * scale))

  const canvas = document.createElement("canvas")
  canvas.width = width
  canvas.height = height
  const ctx = canvas.getContext("2d")
  if (!ctx) throw new Error("canvas 2d недоступен")
  ctx.drawImage(img, 0, 0, width, height)

  return new Promise((resolve, reject) => {
    canvas.toBlob(
      (blob) => (blob ? resolve(blob) : reject(new Error("Не удалось сжать картинку"))),
      "image/jpeg",
      quality,
    )
  })
}
