/// <reference types="vite/client" />

interface ImportMetaEnv {
  // База API. В dev пусто (ходим через Vite-proxy на :8000), в prod — тот же origin за nginx.
  readonly VITE_API_BASE?: string
}

interface ImportMeta {
  readonly env: ImportMetaEnv
}
