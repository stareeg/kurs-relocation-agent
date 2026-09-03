import {
  AlertTriangle,
  Check,
  ChevronDown,
  ChevronUp,
  Copy,
  Download,
  ExternalLink,
  Loader2,
} from "lucide-react"
import { useState } from "react"
import { toast } from "sonner"
import { useQuery } from "@tanstack/react-query"
import type { components } from "@/api/schema"
import { api } from "@/api/client"
import { downloadExtensionZip } from "@/api/extension"
import { Button } from "@/components/ui/button"
import { useAuthStatusQuery } from "@/features/auth/use-auth-status"
import { usePersistedBoolean } from "@/lib/use-persisted-boolean"
import { copyText } from "@/lib/clipboard"
import { readLastAuthToken } from "./last-auth-token"

type ExtensionSetup = components["schemas"]["ExtensionSetupResponse"]

const CHROME_EXTENSIONS_URL = "chrome://extensions"
const EXTENSION_DOWNLOADED_KEY = "extension.zipDownloaded"

// dist_ready нужен только для предупреждения «сборки нет» до клика по кнопке скачивания;
// extension_dir (путь на диске сервера) фронт больше не показывает — на VM он бессмыслен (EX-14).
function useExtensionSetup() {
  return useQuery({
    queryKey: ["extension-setup"],
    queryFn: () => api.get<ExtensionSetup>("/api/meta/extension"),
    staleTime: 60_000,
  })
}

function StepCard({
  step,
  title,
  children,
}: {
  step: number
  title: string
  children: React.ReactNode
}) {
  return (
    <article className="rounded-xl border bg-white p-5">
      <div className="mb-3 flex items-center gap-3">
        <span
          className="inline-flex size-7 shrink-0 items-center justify-center rounded-full bg-slate-900 text-sm font-semibold tabular-nums text-white"
          aria-hidden
        >
          {step}
        </span>
        <h3 className="text-base font-semibold text-slate-900">{title}</h3>
      </div>
      <div className="space-y-3 pl-10 text-sm leading-relaxed text-slate-600">{children}</div>
    </article>
  )
}

/** Сравнить semver-строки «0.4.0» < «0.5.1». Некорректная/отсутствующая installed → unknown. */
function isOutdated(
  installed: string | null | undefined,
  latest: string | null | undefined,
): boolean {
  if (!installed || !latest) return false
  const a = installed.split(".").map((n) => Number.parseInt(n, 10))
  const b = latest.split(".").map((n) => Number.parseInt(n, 10))
  for (let i = 0; i < Math.max(a.length, b.length); i++) {
    const ai = a[i] ?? 0
    const bi = b[i] ?? 0
    if (ai < bi) return true
    if (ai > bi) return false
  }
  return false
}

function CopyAuthTokenButton() {
  const [copied, setCopied] = useState(false)
  const token = readLastAuthToken()

  function handleCopy() {
    if (!token) {
      toast.error("Сначала войдите токеном из бота — тогда его можно скопировать сюда")
      return
    }
    void copyText(token).then((ok) => {
      if (!ok) {
        toast.error("Не удалось скопировать")
        return
      }
      setCopied(true)
      toast.success("Токен скопирован")
      window.setTimeout(() => setCopied(false), 1500)
    })
  }

  return (
    <Button type="button" size="sm" variant="outline" onClick={handleCopy}>
      {copied ? (
        <Check className="size-3.5 text-emerald-600" strokeWidth={2.5} />
      ) : (
        <Copy className="size-3.5" strokeWidth={2} />
      )}
      {copied ? "Скопировано" : "Копировать токен"}
    </Button>
  )
}

// EX-14: скачивание zip — основной путь установки (путь на диске сервера пользователю не нужен).
// Ошибку показываем текстом под кнопкой, а не только тостом: 409 «сборка не найдена» должно
// остаться на экране, пока пользователь не пересобрал dist.
function DownloadCard({
  distReady,
  latestVersion,
  installedVersion,
}: {
  distReady: boolean | undefined
  latestVersion: string | null | undefined
  installedVersion: string | null | undefined
}) {
  const [pending, setPending] = useState(false)
  const [error, setError] = useState<string | null>(null)
  const [downloaded, setDownloaded] = usePersistedBoolean(EXTENSION_DOWNLOADED_KEY)

  async function handleDownload() {
    setPending(true)
    setError(null)
    try {
      await downloadExtensionZip()
      setDownloaded(true)
      toast.success("Архив скачан — распакуйте его в любую папку")
    } catch (err) {
      setError(err instanceof Error ? err.message : "Не удалось скачать архив")
    } finally {
      setPending(false)
    }
  }

  const outdated = isOutdated(installedVersion, latestVersion)
  // Жёлтый акцент — только пока человек ни разу не скачивал zip в этом браузере и расширение
  // ещё не отчиталось установленной версией.
  const needsAttention = !downloaded && !installedVersion

  return (
    <section className="rounded-xl border bg-white p-5">
      <div className="flex flex-wrap items-center justify-between gap-3">
        <div className="space-y-1">
          <h2 className="text-base font-semibold text-slate-900">Скачайте расширение</h2>
          {latestVersion ? (
            <p className="text-sm text-slate-600">
              {outdated ? (
                <>Вышла новая версия {latestVersion} — скачайте ниже.</>
              ) : installedVersion ? (
                <>У вас последняя версия {installedVersion}.</>
              ) : (
                <>Текущая версия {latestVersion}.</>
              )}
            </p>
          ) : (
            <p className="text-sm text-slate-600">Готовый архив — распакуйте по шагам ниже.</p>
          )}
          <p className="flex items-center gap-1.5 text-sm text-slate-600">
            {needsAttention && (
              <AlertTriangle
                className="size-4 shrink-0 text-amber-500"
                strokeWidth={2}
                aria-label="Обратите внимание"
              />
            )}
            Расширение нужно для оценки вакансий.
          </p>
          <p className="text-sm text-slate-500">
            Поддерживаются hh.ru, getmatch.ru, career.habr.ru
          </p>
        </div>
        <Button type="button" disabled={pending} onClick={() => void handleDownload()}>
          {pending ? (
            <Loader2 className="size-4 animate-spin" strokeWidth={2} />
          ) : (
            <Download className="size-4" strokeWidth={2} />
          )}
          {downloaded ? "Скачать ещё раз" : "Скачать расширение"}
        </Button>
      </div>
      {distReady === false && (
        <p className="mt-3 text-sm text-amber-700">Сборка расширения не найдена на сервере.</p>
      )}
      {error && (
        <p className="mt-3 text-sm text-red-700" role="alert">
          {error}
        </p>
      )}
    </section>
  )
}

function InstallGuideSection({ botLink }: { botLink: string | null }) {
  const [open, setOpen] = useState(false)

  return (
    <section className="rounded-xl border bg-white">
      <button
        type="button"
        onClick={() => setOpen((v) => !v)}
        aria-expanded={open}
        className="flex w-full items-center justify-between gap-3 px-5 py-4 text-left"
      >
        <span className="text-base font-bold text-slate-900">
          Как установить расширение в Chrome
        </span>
        {open ? (
          <ChevronUp className="size-4 shrink-0 text-slate-500" strokeWidth={2} />
        ) : (
          <ChevronDown className="size-4 shrink-0 text-slate-500" strokeWidth={2} />
        )}
      </button>
      {open && (
        <div className="space-y-3 border-t px-5 pb-5 pt-4">
          <StepCard step={1} title="Распакуйте архив">
            <p>В любую папку, откуда удалять её не планируете.</p>
          </StepCard>

          <StepCard step={2} title="Откройте страницу расширений по ссылке">
            <div className="flex items-start justify-between gap-3 rounded-lg bg-slate-50 px-3 py-2.5">
              <code className="min-w-0 flex-1 whitespace-pre-wrap break-all font-mono text-sm text-slate-800">
                {CHROME_EXTENSIONS_URL}
              </code>
              {/* chrome:// из https-страницы Chrome часто блокирует — оставляем href как
                  явный клик пользователя; если вкладка не откроется, адрес всё равно виден. */}
              <Button type="button" variant="outline" size="sm" className="h-8 shrink-0 px-2.5 text-sm" asChild>
                <a href={CHROME_EXTENSIONS_URL} target="_blank" rel="noopener noreferrer">
                  <ExternalLink className="size-3.5" strokeWidth={2} />
                  Открыть
                </a>
              </Button>
            </div>
          </StepCard>

          <StepCard step={3} title="Включите «Режим разработчика»">
            <p>Переключатель — в правом верхнем углу открывшейся страницы.</p>
          </StepCard>

          <StepCard step={4} title="Подключите папку расширения">
            <p>
              Нажмите{" "}
              <strong className="font-medium text-slate-800">«Загрузить распакованное»</strong>.
            </p>
          </StepCard>

          <StepCard step={5} title="Вставьте токен авторизации">
            <p>
              Зайдите на площадку, например, hh.ru в любой раздел и вставьте токен{" "}
              {botLink ? (
                <a
                  href={botLink}
                  target="_blank"
                  rel="noopener noreferrer"
                  className="inline-flex items-center gap-1 font-medium text-sky-700 underline-offset-2 hover:underline"
                >
                  из бота
                  <ExternalLink className="size-3.5" strokeWidth={2} />
                </a>
              ) : (
                <span>из бота</span>
              )}{" "}
              в панель снизу.
            </p>
            <CopyAuthTokenButton />
          </StepCard>
        </div>
      )}
    </section>
  )
}

/** «Скачать расширение» + «Инструкция по установке» — переехали из «Расширения» в «Параметры»
 * (там же живут остальные разовые настройки окружения), чтобы «Расширение» отдавали целиком под
 * пайплайн площадок. */
export function ExtensionInstallSection() {
  const { data: setup } = useExtensionSetup()
  const { data: authStatus } = useAuthStatusQuery()

  const botUsername = authStatus?.bot_username
  const botLink = botUsername ? `https://t.me/${botUsername}` : null

  return (
    <div className="space-y-4">
      <DownloadCard
        distReady={setup?.dist_ready}
        latestVersion={setup?.latest_version}
        installedVersion={setup?.installed_version}
      />
      <InstallGuideSection botLink={botLink} />
    </div>
  )
}
