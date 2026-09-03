import { useMemo, useState, type KeyboardEvent } from "react"
import { Input } from "@/components/ui/input"
import { Popover, PopoverAnchor, PopoverContent } from "@/components/ui/popover"
import {
  formatCitySuggestion,
  type CitySuggestion,
} from "@/lib/cities"
import { cn } from "@/lib/utils"

const MAX_VISIBLE = 12

export type { CitySuggestion }

export function CityInput({
  value,
  onChange,
  onSelect,
  suggestions,
  placeholder,
  className,
}: {
  value: string
  onChange: (city: string) => void
  onSelect?: (item: CitySuggestion) => void
  suggestions: CitySuggestion[]
  placeholder?: string
  className?: string
}) {
  const [open, setOpen] = useState(false)
  const [highlight, setHighlight] = useState(0)

  const filtered = useMemo(() => {
    const q = value.trim().toLocaleLowerCase("ru")
    const pool = q
      ? suggestions.filter((item) => {
          const hay = [item.city, item.country, ...(item.aliases ?? [])]
            .join(" ")
            .toLocaleLowerCase("ru")
          return hay.includes(q)
        })
      : suggestions
    return pool.slice(0, MAX_VISIBLE)
  }, [suggestions, value])

  function choose(item: CitySuggestion) {
    if (onSelect) onSelect(item)
    else onChange(item.city)
    setOpen(false)
  }

  function onKeyDown(e: KeyboardEvent<HTMLInputElement>) {
    if (e.key === "ArrowDown") {
      e.preventDefault()
      if (!open) {
        setOpen(true)
        return
      }
      setHighlight((i) => (filtered.length === 0 ? 0 : (i + 1) % filtered.length))
      return
    }
    if (e.key === "ArrowUp") {
      e.preventDefault()
      setHighlight((i) =>
        filtered.length === 0 ? 0 : (i - 1 + filtered.length) % filtered.length,
      )
      return
    }
    if (e.key === "Enter" && open && filtered[highlight]) {
      e.preventDefault()
      choose(filtered[highlight])
      return
    }
    if (e.key === "Escape") setOpen(false)
  }

  return (
    <Popover open={open && filtered.length > 0} onOpenChange={setOpen}>
      <PopoverAnchor asChild>
        <Input
          value={value}
          onChange={(e) => {
            onChange(e.target.value)
            setHighlight(0)
            setOpen(true)
          }}
          onFocus={() => setOpen(true)}
          onKeyDown={onKeyDown}
          placeholder={placeholder}
          className={className}
          autoComplete="off"
          spellCheck={false}
          role="combobox"
          aria-expanded={open && filtered.length > 0}
          aria-autocomplete="list"
        />
      </PopoverAnchor>
      <PopoverContent
        className="w-[var(--radix-popover-anchor-width)] p-1"
        onOpenAutoFocus={(e) => e.preventDefault()}
        onCloseAutoFocus={(e) => e.preventDefault()}
      >
        <ul role="listbox" className="max-h-64 overflow-auto">
          {filtered.map((item, index) => (
            <li key={`${item.city}-${item.source ?? ""}`}>
              <button
                type="button"
                role="option"
                aria-selected={index === highlight}
                onMouseDown={(e) => e.preventDefault()}
                onClick={() => choose(item)}
                onMouseEnter={() => setHighlight(index)}
                className={cn(
                  "flex w-full rounded-md px-2 py-1.5 text-left text-sm transition-colors",
                  index === highlight ? "bg-accent text-foreground" : "text-muted-foreground",
                )}
              >
                {formatCitySuggestion(item)}
              </button>
            </li>
          ))}
        </ul>
      </PopoverContent>
    </Popover>
  )
}
