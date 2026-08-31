/// <reference types="vite/client" />

interface ImportMetaEnv {
  /** Base URL of the Custode REST API, e.g. https://api.custode.tuodominio.it */
  readonly VITE_API_BASE_URL?: string;
}

interface ImportMeta {
  readonly env: ImportMetaEnv;
}
