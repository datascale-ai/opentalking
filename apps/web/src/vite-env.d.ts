/// <reference types="vite/client" />

interface ImportMetaEnv {
  readonly VITE_API_BASE?: string;
  /** Max chat bubbles to show (most recent). 0 or unset = show all. */
  readonly VITE_CHAT_MAX_VISIBLE?: string;
}

interface ImportMeta {
  readonly env: ImportMetaEnv;
}
