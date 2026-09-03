import * as React from "react"
import { ChevronDown, ChevronLeft, ChevronRight } from "lucide-react"
import { DayPicker, getDefaultClassNames } from "react-day-picker"
import { ru } from "react-day-picker/locale"

import { cn } from "@/lib/utils"
import { buttonVariants } from "@/components/ui/button"

// Календарь дня (RD-2/5/6 granularity="day") — react-day-picker v10, токены дизайн-системы под
// остальные примитивы (select.tsx/popover.tsx). Месяц/год выбираются отдельными гридами
// в date-picker.tsx (у react-day-picker нет режима «только месяц»/«только год»).
function Calendar({
  className,
  classNames,
  captionLayout = "label",
  ...props
}: React.ComponentProps<typeof DayPicker>) {
  const defaultClassNames = getDefaultClassNames()
  const withDropdowns =
    captionLayout === "dropdown" ||
    captionLayout === "dropdown-years" ||
    captionLayout === "dropdown-months"

  return (
    <DayPicker
      locale={ru}
      showOutsideDays
      captionLayout={captionLayout}
      className={cn("p-0", className)}
      classNames={{
        root: cn(defaultClassNames.root, "w-fit"),
        months: cn(defaultClassNames.months, "relative flex gap-4"),
        month: cn(defaultClassNames.month, "flex flex-col gap-3"),
        nav: cn(
          defaultClassNames.nav,
          withDropdowns ? "hidden" : "absolute inset-x-0 top-0 flex items-center justify-between",
        ),
        button_previous: cn(
          buttonVariants({ variant: "ghost", size: "icon-sm" }),
          "text-muted-foreground",
        ),
        button_next: cn(
          buttonVariants({ variant: "ghost", size: "icon-sm" }),
          "text-muted-foreground",
        ),
        month_caption: cn(
          defaultClassNames.month_caption,
          withDropdowns
            ? "flex h-8 items-center justify-center"
            : "flex h-8 items-center justify-center px-8 text-sm font-medium text-foreground",
        ),
        dropdowns: cn(
          defaultClassNames.dropdowns,
          "flex w-full items-center justify-center gap-1.5",
        ),
        // Select и caption_label — не два независимых виджета: react-day-picker рендерит
        // невидимый нативный <select> поверх видимого span-лейбла (a11y-паттерн), чтобы клик и
        // клавиатура работали как обычный select, а на экране была своя стилизованная подпись.
        // Без этого select показывает свой текст рядом с текстом лейбла — год/месяц дублируются.
        dropdown_root: cn(
          defaultClassNames.dropdown_root,
          "relative inline-flex h-8 items-center rounded-md border border-input bg-card px-2 focus-within:ring-2 focus-within:ring-ring",
        ),
        dropdown: cn(
          defaultClassNames.dropdown,
          "absolute inset-0 z-10 cursor-pointer appearance-none opacity-0",
        ),
        months_dropdown: cn(defaultClassNames.months_dropdown),
        years_dropdown: cn(defaultClassNames.years_dropdown),
        caption_label: cn(
          defaultClassNames.caption_label,
          withDropdowns
            ? "pointer-events-none flex items-center gap-1 text-sm font-medium text-foreground"
            : "text-sm font-medium text-foreground",
        ),
        weekdays: cn(defaultClassNames.weekdays, "flex"),
        weekday: cn(
          defaultClassNames.weekday,
          "w-8 text-center text-xs font-medium text-muted-foreground",
        ),
        week: cn(defaultClassNames.week, "mt-1 flex"),
        day: cn(defaultClassNames.day, "p-0 text-center"),
        day_button: cn(
          buttonVariants({ variant: "ghost" }),
          "size-8 rounded-md p-0 font-normal text-foreground hover:bg-accent aria-selected:opacity-100",
        ),
        today: "text-foreground font-semibold",
        selected:
          "[&>button]:bg-primary [&>button]:text-primary-foreground [&>button]:hover:bg-primary [&>button]:hover:text-primary-foreground",
        outside: "text-muted-foreground",
        disabled: "text-muted-foreground opacity-50",
        ...classNames,
      }}
      components={{
        Chevron: ({ orientation, className: chevronClassName, ...chevronProps }) => {
          if (orientation === "left")
            return <ChevronLeft className={cn("size-4", chevronClassName)} {...chevronProps} />
          if (orientation === "down")
            return <ChevronDown className={cn("size-4", chevronClassName)} {...chevronProps} />
          return <ChevronRight className={cn("size-4", chevronClassName)} {...chevronProps} />
        },
      }}
      {...props}
    />
  )
}

export { Calendar }
