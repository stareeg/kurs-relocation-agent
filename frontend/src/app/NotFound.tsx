import { useLocation } from "react-router-dom"
import { Link2Off } from "lucide-react"
import { EmptyState } from "@/components/ui/empty-state"

/**
 * Экран несуществующего адреса (Этап 1.6 плана `plans/ui_slop_cleanup_2026_08_25.md`).
 *
 * Раньше любой неизвестный путь молча уходил редиректом на доску вакансий: опечатка в адресе
 * и битая ссылка выглядели как «раздел удалили». Теперь редирект остался только у корня `/`
 * (`HomeRedirect`), а всё остальное честно говорит, что адреса нет, и показывает какого именно.
 *
 * Живёт внутри `AppShell`, а не рядом с ним: с боковым меню у человека остаётся обычная
 * навигация, а не один-единственный выход кнопкой.
 */
export function NotFound() {
  const { pathname } = useLocation()
  return (
    <EmptyState
      variant="filtered"
      icon={Link2Off}
      title="Такой страницы нет"
      note={`Адрес ${pathname} не соответствует ни одному разделу. Возможно, ссылка устарела или в ней опечатка — разделы открываются из меню слева.`}
      action={{ label: "На доску вакансий", to: "/jobs" }}
    />
  )
}
