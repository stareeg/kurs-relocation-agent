import { ChevronsRight, FileText } from "lucide-react"
import { ErrorState } from "@/components/ui/empty-state"
import { Skeleton, SkeletonCard } from "@/components/ui/skeleton"
import { OnboardingHint } from "@/components/ui/tooltip"
import { usePersistedBoolean } from "@/lib/use-persisted-boolean"
import { ONBOARDING_HINT_IDS, useOnboardingHints } from "@/lib/use-onboarding-hints"
import { AtsFitProvider } from "./ats-fit-context"
import { ScoreFixApplyProvider } from "./resume-score-apply-context"
import { ResumeChat } from "./ResumeChat"
import { ResumeCollapseProvider } from "./ResumeCollapseProvider"
import { ResumeForm } from "./ResumeForm"
import { ResumePdfSlotProvider } from "./resume-pdf-slot"
import { ResumeScoreCard } from "./ResumeScoreCard"
import { useResumeData } from "./use-resume"

function FormSkeleton() {
  return (
    <div className="space-y-4 p-6">
      <Skeleton className="h-10 w-full" />
      {[0, 1, 2].map((i) => (
        <SkeletonCard key={i} className="h-40 w-full" />
      ))}
    </div>
  )
}

export function ResumePage() {
  const { data, isLoading, isError, refetch } = useResumeData()
  const { shouldShow, dismissHint } = useOnboardingHints()

  const showFillHint = shouldShow(ONBOARDING_HINT_IDS.resumeFillBasics)
  // Сворачивание левой панели (по образцу Screenings/PitchScript) — состояние переживает
  // перезагрузку, свёрнутая панель оставляет только вертикальную полосу-кнопку «Панель».
  const [panelCollapsed, setPanelCollapsed] = usePersistedBoolean(
    "copilot.resume-side-collapsed",
    false,
  )

  return (
    <AtsFitProvider>
      <ScoreFixApplyProvider>
        <ResumeCollapseProvider>
        <ResumePdfSlotProvider>
          <div className="flex min-h-0 flex-1 flex-col">
            <div className="flex min-h-0 flex-1 flex-col lg:flex-row">
              <aside
                className={
                  "order-2 flex min-h-0 shrink-0 flex-col border-b bg-white lg:order-1 lg:border-b-0 lg:border-r " +
                  (panelCollapsed ? "lg:w-11" : "lg:w-[30.8rem]")
                }
              >
                {panelCollapsed ? (
                  <button
                    type="button"
                    onClick={() => setPanelCollapsed(false)}
                    title="Развернуть панель"
                    aria-label="Развернуть панель"
                    className="flex h-full w-full flex-col items-center gap-2 py-3 text-slate-500 transition-colors hover:bg-slate-50"
                  >
                    <ChevronsRight className="size-4 shrink-0" strokeWidth={2} />
                    <span className="[writing-mode:vertical-rl] text-xs font-medium tracking-wide text-slate-600">
                      Панель
                    </span>
                  </button>
                ) : (
                  <div className="flex min-h-0 flex-1 flex-col">
                    {/* Скоринг в левой панели; балл — в основной колонке над «Профилем». */}
                    <div className="min-h-0 flex-1 overflow-y-auto">
                      <div className="px-2 pt-2 pb-3">
                        <ResumeScoreCard onCollapsePanel={() => setPanelCollapsed(true)} />
                      </div>
                    </div>
                  </div>
                )}
              </aside>
              {isLoading ? (
                <div className="order-1 min-h-0 flex-1 overflow-y-auto lg:order-2">
                  <FormSkeleton />
                </div>
              ) : isError || !data ? (
                <div className="order-1 min-h-0 flex-1 lg:order-2">
                  <ErrorState
                    icon={FileText}
                    title="Резюме недоступно"
                    note="Не удалось загрузить резюме."
                    action={{ label: "Повторить", onClick: () => void refetch() }}
                  />
                </div>
              ) : (
                // Форма скроллится сама; чат прижат снизу колонки и не входит в её overflow —
                // иначе при скролле формы браузер ещё и красит ленту сообщений.
                <div
                  id="screen-start-resume"
                  className="order-1 flex min-h-0 flex-1 flex-col lg:order-2"
                >
                  {showFillHint && (
                    <OnboardingHint
                      open
                      onDismiss={() => dismissHint(ONBOARDING_HINT_IDS.resumeFillBasics)}
                      content="Заполните критерии поиска и блоки опыта. Можно править вручную или через «Подогнать под ATS»."
                      side="bottom"
                      align="start"
                      autoHideMs={6000}
                    >
                      <div className="border-b border-sky-100 bg-sky-50/70 px-4 py-2.5 text-sm text-sky-900 lg:px-6">
                        Сначала критерии поиска и опыт — от них зависит оценка вакансий. Если
                        застряли — наведите на «Что делать?» внизу меню.
                      </div>
                    </OnboardingHint>
                  )}
                  <div className="min-h-0 flex-1 overflow-y-auto bg-slate-50/30" data-resume-scroll>
                    <ResumeForm data={data} />
                  </div>
                  <ResumeChat className="shrink-0" />
                </div>
              )}
            </div>
          </div>
        </ResumePdfSlotProvider>
      </ResumeCollapseProvider>
      </ScoreFixApplyProvider>
    </AtsFitProvider>
  )
}
