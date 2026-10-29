/// <reference types="vite/client" />

interface ImportMetaEnv {
  readonly VITE_SHOW_POLICY_ATTACHMENT?: string;
}

interface ImportMeta {
  readonly env: ImportMetaEnv;
}

declare const __APP_NAME__: string;
