/**
 * Clipboard helpers that survive Safari / iOS quirks:
 * - `writeText` often needs a user gesture; after `await` Safari throws NotAllowedError
 * - private mode / missing API → textarea + `execCommand("copy")` fallback
 */

export async function copyText(text: string): Promise<boolean> {
  const value = text ?? ""
  if (!value) return false

  try {
    if (navigator.clipboard?.writeText) {
      await navigator.clipboard.writeText(value)
      return true
    }
  } catch {
    /* fall through to execCommand */
  }

  try {
    const ta = document.createElement("textarea")
    ta.value = value
    ta.setAttribute("readonly", "")
    ta.style.position = "fixed"
    ta.style.top = "0"
    ta.style.left = "0"
    ta.style.opacity = "0"
    document.body.appendChild(ta)
    ta.focus()
    ta.select()
    ta.setSelectionRange(0, value.length)
    const ok = document.execCommand("copy")
    document.body.removeChild(ta)
    return ok
  } catch {
    return false
  }
}
