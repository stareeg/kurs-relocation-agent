import { useMemo } from "react"
import { useQuery } from "@tanstack/react-query"
import { fetchCities, type CitySuggestionOut } from "@/api/meta"
import {
  mergeCitySuggestions,
  type CitySuggestion,
} from "@/lib/cities"

function fromApi(item: CitySuggestionOut): CitySuggestion {
  return {
    city: item.city,
    country: item.country || undefined,
    timezone: item.timezone || undefined,
    utcOffset: item.utc_offset || undefined,
    overlapEmea: item.overlap_emea,
    source: item.source,
  }
}

export function useCitySuggestions(experienceAreas: string[]): CitySuggestion[] {
  const { data } = useQuery({
    queryKey: ["meta", "cities"],
    queryFn: fetchCities,
    staleTime: 60_000,
    retry: false,
  })
  const areasKey = experienceAreas.join("\0")
  return useMemo(() => {
    const areas = areasKey === "" ? [] : areasKey.split("\0")
    const fromApiItems = (data?.items ?? []).map(fromApi)
    return mergeCitySuggestions(fromApiItems, areas)
  }, [data, areasKey])
}
