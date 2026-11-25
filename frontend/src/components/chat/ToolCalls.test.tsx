import { render, screen } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { describe, expect, it, vi } from "vitest";
import { newStream, reduceStream, type ToolCallView } from "../../stores/chat";
import { toSpeech } from "./SpeakButton";
import { ToolCalls } from "./ToolCalls";

const awaiting: ToolCallView = {
  callId: "c1",
  tool: "file_write",
  risk: "write",
  summary: "Crear C:/proyecto/NOTAS.md (8 caracteres, 2 líneas)",
  arguments: { path: "C:/proyecto/NOTAS.md", content: "# Notas\n" },
  status: "awaiting",
  resultSummary: null,
  expiresAt: Date.now() + 120_000,
};

describe("ToolCalls", () => {
  it("muestra los argumentos reales y pide permiso", async () => {
    const onConfirm = vi.fn();
    render(<ToolCalls tools={[awaiting]} onConfirm={onConfirm} />);
    expect(screen.getByText("Escribir archivo")).toBeInTheDocument();
    expect(screen.getByText("escritura")).toBeInTheDocument();
    expect(screen.getByText("esperando tu permiso")).toBeInTheDocument();
    expect(screen.getByText("C:/proyecto/NOTAS.md")).toBeInTheDocument();
    await userEvent.click(screen.getByRole("button", { name: "Permitir" }));
    expect(onConfirm).toHaveBeenCalledWith("c1", true);
    await userEvent.click(screen.getByRole("button", { name: "Denegar" }));
    expect(onConfirm).toHaveBeenCalledWith("c1", false);
  });

  it("renderiza el historial guardado sin botones", () => {
    render(
      <ToolCalls
        tools={[
          { call_id: "x", tool: "file_read", risk: "read", status: "ok", decision: "auto",
            summary: "Leídas 3 líneas de miapp/README.md" },
        ]}
      />,
    );
    expect(screen.getByText("Leer archivo")).toBeInTheDocument();
    expect(screen.getByText("completada")).toBeInTheDocument();
    expect(screen.queryByRole("button", { name: "Permitir" })).not.toBeInTheDocument();
  });
});

describe("reduceStream con herramientas", () => {
  it("sigue el ciclo call -> confirm_request -> result", () => {
    let s = newStream("r1", "c", "hola");
    s = reduceStream(s, {
      type: "tool.call", request_id: "r1", call_id: "k", tool: "file_write",
      arguments: { path: "a" }, risk: "write", summary: "Crear a",
    });
    expect(s.tools[0]?.status).toBe("running");
    s = reduceStream(s, {
      type: "tool.confirm_request", request_id: "r1", call_id: "k", tool: "file_write",
      summary: "Crear a", arguments: { path: "a" }, risk: "write", expires_in: 120,
    });
    expect(s.tools[0]?.status).toBe("awaiting");
    expect(s.tools[0]?.expiresAt).toBeGreaterThan(Date.now());
    s = reduceStream(s, {
      type: "tool.result", request_id: "r1", call_id: "k", status: "denied", summary: "Denegada por ti",
    });
    expect(s.tools).toHaveLength(1);
    expect(s.tools[0]).toMatchObject({ status: "denied", resultSummary: "Denegada por ti", expiresAt: null });
  });
});

describe("toSpeech", () => {
  it("quita Markdown y bloques de código antes de leer en voz alta", () => {
    const text = toSpeech("# Título\n\nUsa **negrita** y `código`.\n\n```py\nprint(1)\n```\n[enlace](https://x.y)");
    expect(text).not.toMatch(/[#*`]/);
    expect(text).toContain("bloque de código omitido");
    expect(text).toContain("enlace");
    expect(text).not.toContain("https://");
  });
});
