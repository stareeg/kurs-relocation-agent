import { ChevronsDownUp, ChevronsUpDown } from "lucide-react"
import { Button } from "@/components/ui/button"
import { cn } from "@/lib/utils"
import { useResumeCollapse } from "./resume-collapse-context"

/** Кнопка «Свернуть все» / «Развернуть все» — внизу блока «Балл резюме», на всю ширину. */
export function ResumeCollapseButton({ className }: { className?: string }) {
  const { collapse, apply } = useResumeCollapse()
  return (
    <Button
      type="button"
      variant="default"
      className={cn("h-9 w-full gap-1.5", className)}
      onClick={() => apply(!collapse)}
    >
      {collapse ? (
        <ChevronsUpDown className="size-3.5" strokeWidth={2} />
      ) : (
        <ChevronsDownUp className="size-3.5" strokeWidth={2} />
      )}
      {collapse ? "Развернуть все" : "Свернуть все"}
    </Button>
  )
}
