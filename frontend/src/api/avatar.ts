import type { components } from "@/api/schema"
import { api } from "@/api/client"

// Аватар владельца (UX6-13): фото профиля Telegram при входе + ручная замена файлом.
export type AvatarMeta = components["schemas"]["AvatarMetaOut"]

/** Байты того же origin (cookie-сессия) — прямой src для `<img>`, без похода за meta. */
export function avatarImageUrl(): string {
  return "/api/profile/avatar/image"
}

export function fetchAvatarMeta() {
  return api.get<AvatarMeta | null>("/api/profile/avatar")
}

export function uploadAvatar(file: Blob) {
  const formData = new FormData()
  formData.append("file", file, "avatar")
  return api.upload<AvatarMeta>("/api/profile/avatar", formData)
}

export function deleteAvatar() {
  return api.del<void>("/api/profile/avatar")
}
