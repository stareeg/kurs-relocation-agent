// Короткая подпись типа документа для чипа/сетки вложений (2026-08-11: txt/md/pdf/docx
// рендерятся иконкой файла, не миниатюрой — превью нечем строить для текстового формата).

const MIME_LABEL: Record<string, string> = {
  "text/plain": "TXT",
  "text/markdown": "MD",
  "application/pdf": "PDF",
  "application/vnd.openxmlformats-officedocument.wordprocessingml.document": "DOCX",
}

/** "PDF" / "DOCX" / … из mime; неизвестный mime → расширение имени файла в верхнем регистре. */
export function documentExtLabel(mime: string, filename?: string | null): string {
  const byMime = MIME_LABEL[mime]
  if (byMime) return byMime
  const name = filename ?? ""
  const dot = name.lastIndexOf(".")
  return dot === -1 ? "ФАЙЛ" : name.slice(dot + 1).toUpperCase()
}
