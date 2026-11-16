import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query"
import { toast } from "sonner"
import {
  getAgentSettings,
  putAgentSettings,
  type AgentConfirmMode,
  type AgentSettings,
} from "@/api/agent"

// Режим подтверждения действий агента (OQ-8, U-1): переключатель у поля ввода, как режим
// автономности в COWORK. Хранится на сервере (account_settings), действует на следующие
// запуски — режим фиксируется на старте запуска. Смена оптимистичная, откат и тост при ошибке.

const KEY = ["agent", "settings"] as const

export function useAgentSettings() {
  const qc = useQueryClient()
  const query = useQuery({ queryKey: KEY, queryFn: getAgentSettings, staleTime: 60_000 })
  const mutation = useMutation({
    mutationFn: (mode: AgentConfirmMode) => putAgentSettings({ confirm_mode: mode }),
    onMutate: async (mode) => {
      await qc.cancelQueries({ queryKey: KEY })
      const prev = qc.getQueryData<AgentSettings>(KEY)
      qc.setQueryData<AgentSettings>(KEY, { confirm_mode: mode })
      return { prev }
    },
    onError: (_err, _mode, ctx) => {
      qc.setQueryData(KEY, ctx?.prev)
      toast.error("Не удалось сменить режим подтверждения")
    },
    onSettled: () => void qc.invalidateQueries({ queryKey: KEY }),
  })
  const mode: AgentConfirmMode = query.data?.confirm_mode === "auto" ? "auto" : "ask"
  return { mode, setMode: mutation.mutate, ready: query.isSuccess }
}
