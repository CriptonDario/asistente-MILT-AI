import { API_BASE } from "../lib/config";
import { useSession } from "../stores/session";
import type { ProblemDetails, TokenResponse } from "../types/api";

/** Error de la API con el código estable del backend (RFC 9457). */
export class ApiError extends Error {
  readonly status: number;
  readonly code: string;
  readonly detail: string | null;
  readonly errors: ProblemDetails["errors"];

  constructor(status: number, problem: Partial<ProblemDetails>) {
    super(problem.detail || problem.title || `Error HTTP ${status}`);
    this.name = "ApiError";
    this.status = status;
    this.code = problem.code ?? "http_error";
    this.detail = problem.detail ?? null;
    this.errors = problem.errors;
  }
}

export function errorMessage(error: unknown): string {
  if (error instanceof ApiError) {
    if (error.code === "validation_error" && error.errors?.length) {
      return error.errors.map((e) => e.msg).join(". ");
    }
    return error.message;
  }
  if (error instanceof TypeError) return "No se puede conectar con el servidor de MILT.";
  return error instanceof Error ? error.message : "Error desconocido.";
}

// --------------------------------------------------------------- refresh token
let refreshInFlight: Promise<string | null> | null = null;

/** Cabecera anti-CSRF que el backend exige al renovar con cookie. */
export const CSRF_HEADERS = { "X-MILT-Client": "web" } as const;

const sleep = (ms: number) => new Promise((resolve) => setTimeout(resolve, ms));

async function doRefresh(attempt = 0): Promise<string | null> {
  try {
    const response = await fetch(`${API_BASE}/auth/refresh`, {
      method: "POST",
      credentials: "include",
      headers: CSRF_HEADERS,
    });
    if (response.status === 409 && attempt === 0) {
      // Otra pestaña acaba de rotar el token: la cookie ya es la nueva, se reintenta.
      await sleep(400);
      return doRefresh(1);
    }
    if (!response.ok) {
      useSession.getState().clear();
      return null;
    }
    const tokens = (await response.json()) as TokenResponse;
    useSession.getState().setSession(tokens);
    return tokens.access_token;
  } catch {
    // Sin red: no se cierra la sesión local, simplemente no hay token nuevo.
    return null;
  }
}

/**
 * Renueva el access token usando la cookie HttpOnly.
 *
 * Es *single-flight*: varias peticiones con 401 simultáneas comparten una sola
 * renovación. Entre pestañas se serializa con Web Locks, porque reutilizar un
 * refresh token ya rotado hace que el backend revoque la sesión entera.
 */
export function refreshAccessToken(): Promise<string | null> {
  if (!refreshInFlight) {
    const run = (): Promise<string | null> => doRefresh();
    const locked: Promise<string | null> =
      typeof navigator !== "undefined" && navigator.locks
        ? navigator.locks.request("milt-refresh", run).then((token) => token)
        : run();
    refreshInFlight = locked.finally(() => {
      refreshInFlight = null;
    });
  }
  return refreshInFlight;
}

/** Devuelve un access token válido, renovándolo si caduca en menos de 30 s. */
export async function getFreshToken(): Promise<string | null> {
  const { accessToken, expiresAt } = useSession.getState();
  if (accessToken && expiresAt && expiresAt - Date.now() > 30_000) return accessToken;
  return refreshAccessToken();
}

// --------------------------------------------------------------- petición base
export interface RequestOptions {
  method?: "GET" | "POST" | "PATCH" | "PUT" | "DELETE";
  body?: unknown;
  query?: Record<string, string | number | boolean | null | undefined>;
  signal?: AbortSignal;
  /** Adjuntar el access token (por defecto sí). */
  auth?: boolean;
}

function buildUrl(path: string, query?: RequestOptions["query"]): string {
  const url = `${API_BASE}${path}`;
  if (!query) return url;
  const params = new URLSearchParams();
  for (const [key, value] of Object.entries(query)) {
    if (value !== undefined && value !== null && value !== "") params.set(key, String(value));
  }
  const qs = params.toString();
  return qs ? `${url}?${qs}` : url;
}

async function parseError(response: Response): Promise<ApiError> {
  try {
    return new ApiError(response.status, (await response.json()) as ProblemDetails);
  } catch {
    return new ApiError(response.status, { title: response.statusText });
  }
}

export async function api<T>(path: string, options: RequestOptions = {}): Promise<T> {
  const { method = "GET", body, query, signal, auth = true } = options;

  const send = (token: string | null): Promise<Response> => {
    const headers: Record<string, string> = { Accept: "application/json" };
    if (body !== undefined) headers["Content-Type"] = "application/json";
    if (auth && token) headers.Authorization = `Bearer ${token}`;
    return fetch(buildUrl(path, query), {
      method,
      headers,
      body: body === undefined ? undefined : JSON.stringify(body),
      credentials: "include",
      signal,
    });
  };

  let response = await send(auth ? useSession.getState().accessToken : null);
  if (response.status === 401 && auth) {
    const token = await refreshAccessToken();
    if (token) response = await send(token);
  }
  if (!response.ok) throw await parseError(response);
  if (response.status === 204) return undefined as T;
  const type = response.headers.get("content-type") ?? "";
  if (type.includes("json")) return (await response.json()) as T;
  return (await response.text()) as T;
}
