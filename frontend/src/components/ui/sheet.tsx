import * as React from "react"
import { Dialog as SheetPrimitive } from "radix-ui"
import { X } from "lucide-react"

import { cn } from "@/lib/utils"

function Sheet(props: React.ComponentProps<typeof SheetPrimitive.Root>) {
  return <SheetPrimitive.Root data-slot="sheet" {...props} />
}

function SheetPortal(props: React.ComponentProps<typeof SheetPrimitive.Portal>) {
  return <SheetPrimitive.Portal data-slot="sheet-portal" {...props} />
}

function SheetOverlay({
  className,
  ...props
}: React.ComponentProps<typeof SheetPrimitive.Overlay>) {
  return (
    <SheetPrimitive.Overlay
      data-slot="sheet-overlay"
      className={cn(
        "fixed inset-0 z-50 bg-foreground/20 backdrop-blur-[1px] data-[state=open]:animate-in data-[state=closed]:animate-out data-[state=closed]:fade-out-0 data-[state=open]:fade-in-0",
        className,
      )}
      {...props}
    />
  )
}

// Правый дровер: ширина под три вкладки (V-01) — 640px по умолчанию хватает вкладке «Решение» и
// не перекрывает вторую колонку канбана на 1280 (X-11); на узких экранах остаётся w-full. Дефолт
// переопределяется через `className`/`style` (решение #12: резиновая ширина ящика вакансии,
// JobDetailDrawer сам тянет и персистит ширину).
function SheetContent({
  className,
  children,
  ...props
}: React.ComponentProps<typeof SheetPrimitive.Content>) {
  return (
    <SheetPortal>
      <SheetOverlay />
      <SheetPrimitive.Content
        data-slot="sheet-content"
        className={cn(
          "fixed inset-y-0 right-0 z-50 flex h-full w-full max-w-[40rem] flex-col gap-0 border-l bg-card shadow-xl outline-none transition-transform",
          "data-[state=open]:animate-in data-[state=closed]:animate-out data-[state=closed]:slide-out-to-right data-[state=open]:slide-in-from-right data-[state=closed]:duration-200 data-[state=open]:duration-300",
          className,
        )}
        {...props}
      >
        {children}
        <SheetPrimitive.Close className="absolute right-4 top-4 rounded-md p-1 text-muted-foreground opacity-80 transition-opacity hover:bg-accent hover:opacity-100 focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-ring">
          <X className="size-4" strokeWidth={2} />
          <span className="sr-only">Закрыть</span>
        </SheetPrimitive.Close>
      </SheetPrimitive.Content>
    </SheetPortal>
  )
}

function SheetHeader({ className, ...props }: React.ComponentProps<"div">) {
  return (
    <div data-slot="sheet-header" className={cn("flex flex-col gap-1 p-6", className)} {...props} />
  )
}

function SheetTitle({ className, ...props }: React.ComponentProps<typeof SheetPrimitive.Title>) {
  return (
    <SheetPrimitive.Title
      data-slot="sheet-title"
      className={cn("pr-8 text-base font-semibold text-foreground", className)}
      {...props}
    />
  )
}

function SheetDescription({
  className,
  ...props
}: React.ComponentProps<typeof SheetPrimitive.Description>) {
  return (
    <SheetPrimitive.Description
      data-slot="sheet-description"
      className={cn("text-sm text-muted-foreground", className)}
      {...props}
    />
  )
}

export { Sheet, SheetContent, SheetHeader, SheetTitle, SheetDescription }
