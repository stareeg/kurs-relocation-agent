import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query"
import { toast } from "sonner"
import { compressImageFile } from "@/lib/compress-image"
import { deleteAvatar, fetchAvatarMeta, uploadAvatar, type AvatarMeta } from "@/api/avatar"

// Аватар владельца (UX6-13): Telegram-фото при входе (bot_app.services.avatar_sync) + ручная
// замена файлом отсюда. `AvatarMeta | null` — источник правды, показывать ли `<img>` в сайдбаре.

const KEY = ["profile", "avatar"] as const

export function useAvatarMeta() {
  return useQuery({ queryKey: KEY, queryFn: fetchAvatarMeta, staleTime: 60_000 })
}

/** Сжимает файл на канвасе (compress-image) перед отправкой — бэкенд нормализует ещё раз сам,
 * но не должен получать по сети то, что заведомо больше нужного маленькой иконке. */
export function useUploadAvatar() {
  const qc = useQueryClient()
  return useMutation({
    mutationFn: async (file: File) => uploadAvatar(await compressImageFile(file)),
    onSuccess: (meta: AvatarMeta) => {
      qc.setQueryData<AvatarMeta | null>(KEY, meta)
      toast.success("Фото профиля обновлено")
    },
    onError: (err: Error) => toast.error(err.message || "Не удалось загрузить фото"),
  })
}

/** Убрать ручную картинку — эффективный аватар падает обратно на Telegram-фото/дефолт. */
export function useDeleteAvatar() {
  const qc = useQueryClient()
  return useMutation({
    mutationFn: deleteAvatar,
    onSuccess: () => void qc.invalidateQueries({ queryKey: KEY }),
    onError: () => toast.error("Не удалось убрать фото"),
  })
}
