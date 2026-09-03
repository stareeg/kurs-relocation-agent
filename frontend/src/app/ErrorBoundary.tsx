import { Component, type ReactNode } from "react"
import { Button } from "@/components/ui/button"
import { downloadLogsBundle } from "@/api/logs"
import { captureError } from "@/lib/error-capture"
import { isChunkLoadError, reloadForDeployRecovery } from "@/lib/chunk-load"

interface Props {
  children: ReactNode
}

interface State {
  hasError: boolean
  downloading: boolean
}

// FR2-18: последняя линия защиты — падение любого компонента больше не белый экран без следа,
// а зафиксированная запись в error-capture (видна в «Логах» и в инцидент-бандле) + понятный экран.
export class ErrorBoundary extends Component<Props, State> {
  state: State = { hasError: false, downloading: false }

  static getDerivedStateFromError(): Partial<State> {
    return { hasError: true }
  }

  componentDidCatch(error: Error, info: { componentStack?: string | null }) {
    // Stale chunk после деплоя: lazy() мог обойти importWithDeployRecovery (Suspense/Safari) —
    // один reload важнее экрана «Что-то сломалось» для нового пользователя.
    if (isChunkLoadError(error)) {
      reloadForDeployRecovery()
      return
    }
    captureError({
      level: "ERROR",
      kind: "boundary",
      message: error.message || "Ошибка рендера",
      stack: [error.stack, info.componentStack].filter(Boolean).join("\n"),
      url: window.location.href,
    })
  }

  private onDownloadLogs = async () => {
    this.setState({ downloading: true })
    try {
      await downloadLogsBundle()
    } finally {
      this.setState({ downloading: false })
    }
  }

  render() {
    if (!this.state.hasError) return this.props.children

    return (
      <div className="flex h-screen flex-col items-center justify-center gap-3 bg-slate-50 px-6 text-center">
        <p className="text-base font-medium text-slate-800">Что-то сломалось на экране</p>
        <p className="max-w-sm text-sm text-slate-500">
          Ошибка сохранена в логи. Скачайте их кнопкой ниже и приложите к описанию проблемы — или
          просто перезагрузите страницу.
        </p>
        <div className="flex items-center gap-2">
          <Button
            type="button"
            variant="outline"
            disabled={this.state.downloading}
            onClick={() => void this.onDownloadLogs()}
          >
            {this.state.downloading ? "Скачиваю…" : "Скачать логи"}
          </Button>
          <Button type="button" onClick={() => window.location.reload()}>
            Перезагрузить
          </Button>
        </div>
      </div>
    )
  }
}
