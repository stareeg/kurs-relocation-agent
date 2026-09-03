// Пословное сравнение текста для подсветки изменений при LLM-перегенерации (легенда, бриф
// подготовки). Простой diff по словам (без LCS-оптимизаций) — тексты короткие, хватает.

export type DiffSegment = {
  text: string
  added: boolean
  removed: boolean
}

// Нормализует текст: убирает разметку акцентов (если есть), схлопывает пробелы.
export function stripMarks(text: string): string {
  return (text || "")
    .replace(/[*_`#>]/g, "")
    .replace(/\s+/g, " ")
    .trim()
}

// Разбивает строку на слова с сохранением разделителей.
function tokenize(text: string): string[] {
  return text.match(/\S+|\s+/g) ?? []
}

// Простейший diff: сравниваем слова, помечаем добавленные. Удаления не показываем
// (регенерация — это замена текста, важны новые куски, а не что пропало).
export function diffWords(current: string, candidate: string): DiffSegment[] {
  const a = tokenize(stripMarks(current))
  const b = tokenize(stripMarks(candidate))
  const segments: DiffSegment[] = []

  // Простой проход: ищем совпадающие окна. Для коротких текстов достаточно LCS-подобного подхода.
  // Используем динамическое программирование для LCS, потом восстанавливаем.
  const n = a.length
  const m = b.length
  if (n === 0 && m === 0) return [{ text: "", added: false, removed: false }]
  if (n === 0) return [{ text: b.join(""), added: true, removed: false }]

  // DP-таблица для LCS
  const dp: number[][] = Array.from({ length: n + 1 }, () => new Array(m + 1).fill(0))
  for (let i = n - 1; i >= 0; i--) {
    for (let j = m - 1; j >= 0; j--) {
      if (a[i] === b[j]) dp[i][j] = dp[i + 1][j + 1] + 1
      else dp[i][j] = Math.max(dp[i + 1][j], dp[i][j + 1])
    }
  }

  let i = 0
  let j = 0
  while (i < n && j < m) {
    if (a[i] === b[j]) {
      segments.push({ text: a[i], added: false, removed: false })
      i++
      j++
    } else if (dp[i + 1][j] >= dp[i][j + 1]) {
      // слово из current пропущено (удалено) — не показываем, чтобы не захламлять
      i++
    } else {
      segments.push({ text: b[j], added: true, removed: false })
      j++
    }
  }
  while (j < m) {
    segments.push({ text: b[j], added: true, removed: false })
    j++
  }
  return segments
}

export function hasChanges(segments: DiffSegment[]): boolean {
  return segments.some((s) => s.added)
}
