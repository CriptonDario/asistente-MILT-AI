import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";
import { useSession } from "../stores/session";
import { ApiError, api, errorMessage, refreshAccessToken } from "./http";

const user = {
  id: "u1",
  email: "a@milt.local",
  display_name: "A",
  role: "admin",
  is_active: true,
  created_at: "2026-01-01T00:00:00Z",
  last_login_at: null,
} as const;

function json(status: number, body: unknown): Response {
  return new Response(JSON.stringify(body), {
    status,
    headers: { "Content-Type": "application/json" },
  });
}

describe("api()", () => {
  const fetchMock = vi.fn<typeof fetch>();

  beforeEach(() => {
    vi.stubGlobal("fetch", fetchMock);
    useSession.setState({ status: "authenticated", accessToken: "viejo", expiresAt: 0, user });
  });
  afterEach(() => {
    fetchMock.mockReset();
    vi.unstubAllGlobals();
  });

  it("renueva el token una sola vez para varias peticiones con 401", async () => {
    let refreshes = 0;
    fetchMock.mockImplementation(async (input, init) => {
      const url = String(input);
      if (url.endsWith("/auth/refresh")) {
        refreshes += 1;
        expect(new Headers(init?.headers).get("X-MILT-Client")).toBe("web");
        return json(200, { access_token: "nuevo", token_type: "bearer", expires_in: 900, user });
      }
      const auth = new Headers(init?.headers).get("Authorization");
      return auth === "Bearer nuevo" ? json(200, { ok: url }) : json(401, { code: "unauthorized" });
    });

    const results = await Promise.all([api("/a"), api("/b"), api("/c")]);
    expect(refreshes).toBe(1);
    expect(results).toHaveLength(3);
    expect(useSession.getState().accessToken).toBe("nuevo");
  });

  it("cierra la sesión si la renovación falla", async () => {
    fetchMock.mockImplementation(async () => json(401, { code: "unauthorized", detail: "no" }));
    await expect(api("/a")).rejects.toBeInstanceOf(ApiError);
    expect(useSession.getState().status).toBe("anonymous");
    expect(useSession.getState().accessToken).toBeNull();
  });

  it("reintenta una vez si otra pestaña está renovando (409)", async () => {
    let calls = 0;
    fetchMock.mockImplementation(async () => {
      calls += 1;
      return calls === 1
        ? json(409, { code: "refresh_in_progress" })
        : json(200, { access_token: "t2", token_type: "bearer", expires_in: 900, user });
    });
    await expect(refreshAccessToken()).resolves.toBe("t2");
    expect(calls).toBe(2);
  });

  it("convierte Problem Details en ApiError legible", async () => {
    fetchMock.mockResolvedValue(
      json(422, {
        code: "validation_error",
        title: "Datos no válidos",
        detail: "x",
        errors: [{ loc: ["body", "email"], msg: "Correo no válido", type: "value_error" }],
      }),
    );
    const error = await api("/x", { auth: false }).catch((e: unknown) => e);
    expect(error).toBeInstanceOf(ApiError);
    expect((error as ApiError).code).toBe("validation_error");
    expect(errorMessage(error)).toBe("Correo no válido");
  });

  it("204 devuelve undefined y añade la query string", async () => {
    fetchMock.mockResolvedValue(new Response(null, { status: 204 }));
    await expect(api("/x", { query: { a: 1, b: undefined, c: "" } })).resolves.toBeUndefined();
    expect(String(fetchMock.mock.calls[0]?.[0])).toBe("/api/v1/x?a=1");
  });
});
