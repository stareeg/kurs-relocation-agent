import { Input } from "@/components/ui/input"

function onlyDigits(s: string): string {
  return s.replace(/\D/g, "")
}

// РФ-номер: +7 (926) 123-45-67. Постепенный ввод форматируется на каждый символ.
function formatRuPhone(digits: string): string {
  const d = digits.slice(0, 11)
  let out = "+7"
  if (d.length > 1) out += " (" + d.slice(1, Math.min(4, d.length))
  if (d.length >= 4) out += ")"
  if (d.length > 4) out += " " + d.slice(4, Math.min(7, d.length))
  if (d.length > 7) out += "-" + d.slice(7, Math.min(9, d.length))
  if (d.length > 9) out += "-" + d.slice(9, 11)
  return out
}

// Без плюса — считаем, что вводят РФ-номер (8 или 9 в начале, как на hh.ru).
// С плюсом и кодом страны не 7 — деградируем до простого "+"-префикса без жёсткой маски.
export function formatPhoneValue(raw: string): string {
  const hadPlus = raw.trim().startsWith("+")
  const digits = onlyDigits(raw)
  if (!digits) return hadPlus ? "+" : ""

  let normalized = digits
  if (!hadPlus) {
    if (normalized[0] === "8") normalized = "7" + normalized.slice(1)
    else if (normalized[0] !== "7") normalized = "7" + normalized
  }

  if (normalized[0] === "7") return formatRuPhone(normalized)
  return "+" + normalized
}

export function PhoneInput({
  value,
  onChange,
  placeholder,
  className,
}: {
  value: string
  onChange: (v: string) => void
  placeholder?: string
  className?: string
}) {
  return (
    <Input
      value={value}
      onChange={(e) => onChange(formatPhoneValue(e.target.value))}
      placeholder={placeholder ?? "+7 (___) ___-__-__"}
      className={className}
      inputMode="tel"
    />
  )
}
