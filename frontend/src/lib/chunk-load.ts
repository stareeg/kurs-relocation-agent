/**
 * After a deploy the running tab still has the old index.html import map.
 * Hover-prefetch or a first click then 404s on `/assets/FooPage-<oldhash>.js`.
 * Chrome caches that rejection, so later `import()` of the same URL also fails
 * until a full reload picks up the new HTML.
 *
 * Safari (iPhone) формулирует иначе — «Importing a module script failed.» — без этого
 * паттерна ErrorBoundary ловит падение, а авто-reload не срабатывает (@nektamol /jobs).
 */

export function isChunkLoadError(err: unknown): boolean {
  const msg = err instanceof Error ? err.message : String(err)
  return /Failed to fetch dynamically imported module|Loading chunk|error loading dynamically imported module|Importing a module script failed/i.test(
    msg,
  )
}

/** Full reload onto the current URL so the tab picks up the new index.html/assets. */
export function reloadForDeployRecovery(): void {
  if (typeof window !== "undefined") {
    window.location.reload()
  }
}

/** Run a dynamic import; on a stale-chunk 404 reload the tab onto the current URL. */
export function importWithDeployRecovery<T>(loader: () => Promise<T>): Promise<T> {
  return loader().catch((err: unknown) => {
    if (isChunkLoadError(err)) {
      reloadForDeployRecovery()
      return new Promise<T>(() => {})
    }
    throw err
  })
}
