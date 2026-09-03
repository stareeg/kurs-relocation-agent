import type { components } from "@/api/schema"
import { api } from "@/api/client"

export type CompanyRegistryItem = components["schemas"]["CompanyRegistryItem"]
export type CompanyRegistryResponse = components["schemas"]["CompanyRegistryResponse"]

/** GET /api/companies — полный реестр с вердиктом из резюме (B-05 / K-01). */
export function fetchCompanies() {
  return api.get<CompanyRegistryResponse>("/api/companies")
}
