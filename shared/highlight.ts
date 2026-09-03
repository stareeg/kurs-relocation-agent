// Общий модуль веб-дровера и панели расширения (V-06): выделение сути пункта плюсов/минусов/
// флагов жирным до тире (или первыми словами, если тире нет) — единственный источник этой
// логики, чтобы обе поверхности резали пункт одинаково. Разбить строку на part «до»/«после»
// вместо готовой HTML/JSX-разметки — рендер (React vs innerHTML+escapeHtml) у поверхностей разный.
export function splitHighlight(text: string): { bold: string; rest: string } {
  if (!text) return { bold: "", rest: "" }
  // Текст до длинного тире (—/–) — основная мысль пункта.
  const dashMatch = text.match(/^(.{3,40}?)\s*[—–]\s*/)
  if (dashMatch) {
    return { bold: dashMatch[1], rest: text.slice(dashMatch[0].length) }
  }
  // Короткий пункт — целиком жирным.
  if (text.length <= 45) return { bold: text, rest: "" }
  // Длинный без тире — жирные первые 3 слова.
  const words = text.split(" ")
  const rest = words.slice(3).join(" ")
  return { bold: words.slice(0, 3).join(" "), rest: rest ? ` ${rest}` : "" }
}
