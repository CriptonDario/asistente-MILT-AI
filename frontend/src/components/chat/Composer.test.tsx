import { render, screen } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { describe, expect, it, vi } from "vitest";
import { Composer } from "./Composer";

describe("Composer", () => {
  it("Enter envía el texto recortado y limpia; Shift+Enter añade una línea", async () => {
    const onSend = vi.fn();
    render(<Composer onSend={onSend} onStop={vi.fn()} streaming={false} />);
    const box = screen.getByRole("textbox", { name: "Mensaje" });

    await userEvent.type(box, "  hola{Shift>}{Enter}{/Shift}mundo  ");
    expect(box).toHaveValue("  hola\nmundo  ");
    await userEvent.keyboard("{Enter}");
    expect(onSend).toHaveBeenCalledWith("hola\nmundo");
    expect(box).toHaveValue("");
  });

  it("no envía mensajes vacíos", async () => {
    const onSend = vi.fn();
    render(<Composer onSend={onSend} onStop={vi.fn()} streaming={false} />);
    expect(screen.getByRole("button", { name: "Enviar mensaje" })).toBeDisabled();
    await userEvent.type(screen.getByRole("textbox", { name: "Mensaje" }), "   {Enter}");
    expect(onSend).not.toHaveBeenCalled();
  });

  it("durante el streaming muestra Detener y no envía", async () => {
    const onSend = vi.fn();
    const onStop = vi.fn();
    render(<Composer onSend={onSend} onStop={onStop} streaming />);
    await userEvent.type(screen.getByRole("textbox", { name: "Mensaje" }), "hola{Enter}");
    expect(onSend).not.toHaveBeenCalled();
    await userEvent.click(screen.getByRole("button", { name: "Detener respuesta" }));
    expect(onStop).toHaveBeenCalledOnce();
  });

  it("adjuntar y micrófono están deshabilitados hasta sus fases", () => {
    render(<Composer onSend={vi.fn()} onStop={vi.fn()} streaming={false} />);
    expect(screen.getByRole("button", { name: /Adjuntar archivos/ })).toBeDisabled();
    expect(screen.getByRole("button", { name: /Hablar/ })).toBeDisabled();
  });
});
