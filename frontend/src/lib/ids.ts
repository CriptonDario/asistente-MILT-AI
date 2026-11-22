/** Identificador de petición compatible con el patrón del backend ([A-Za-z0-9_-]{1,64}). */
export function newRequestId(): string {
  return crypto.randomUUID().replaceAll("-", "");
}
