import { render, screen } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { describe, expect, it, vi } from "vitest";
import type { DocumentInfo } from "../../types/api";
import { Composer, validateUpload } from "./Composer";

describe("Composer", () => {
  it("Enter envía el texto recortado y limpia; Shift+Enter añade una línea", async () => {
    const onSend = vi.fn();
    render(<Composer onSend={onSend} onStop={vi.fn()} streaming={false} />);
    const box = screen.getByRole("textbox", { name: "Mensaje" });

    await userEvent.type(box, "  hola{Shift>}{Enter}{/Shift}mundo  ");
    expect(box).toHaveValue("  hola\nmundo  ");
    await userEvent.keyboard("{Enter}");
    expect(onSend).toHaveBeenCalledWith("hola\nmundo", []);
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

  it("el micrófono sigue deshabilitado hasta la Fase 5", () => {
    render(<Composer onSend={vi.fn()} onStop={vi.fn()} streaming={false} />);
    expect(screen.getByRole("button", { name: /Hablar/ })).toBeDisabled();
    expect(screen.getByRole("button", { name: "Adjuntar documentos" })).toBeEnabled();
  });

  it("adjunta documentos listos y los envía con el mensaje", async () => {
    const onSend = vi.fn();
    render(
      <Composer
        onSend={onSend}
        onStop={vi.fn()}
        streaming={false}
        documents={[doc("d1", "informe.pdf", "ready"), doc("d2", "borrador.docx", "processing")]}
      />,
    );
    await userEvent.click(screen.getByRole("button", { name: "Adjuntar documentos" }));
    expect(screen.queryByText("borrador.docx")).not.toBeInTheDocument();
    await userEvent.click(screen.getByRole("checkbox"));
    expect(screen.getByLabelText("Adjuntos")).toHaveTextContent("informe.pdf");
    await userEvent.type(screen.getByRole("textbox", { name: "Mensaje" }), "Resume{Enter}");
    expect(onSend).toHaveBeenCalledWith("Resume", ["d1"]);
  });

  it("no deja enviar hasta que el adjunto subido termina de procesarse", async () => {
    const onSend = vi.fn();
    const uploaded = doc("d9", "nuevo.txt", "processing");
    const onUpload = vi.fn().mockResolvedValue(uploaded);
    const { rerender } = render(
      <Composer onSend={onSend} onStop={vi.fn()} streaming={false} documents={[]} onUpload={onUpload} />,
    );
    const file = new File(["hola"], "nuevo.txt", { type: "text/plain" });
    await userEvent.upload(screen.getByTestId("file-input"), file);
    expect(onUpload).toHaveBeenCalledWith(file);
    rerender(
      <Composer onSend={onSend} onStop={vi.fn()} streaming={false} documents={[uploaded]} onUpload={onUpload} />,
    );
    await userEvent.type(screen.getByRole("textbox", { name: "Mensaje" }), "hola");
    expect(screen.getByRole("button", { name: "Enviar mensaje" })).toBeDisabled();
    rerender(
      <Composer
        onSend={onSend}
        onStop={vi.fn()}
        streaming={false}
        documents={[{ ...uploaded, status: "ready" }]}
        onUpload={onUpload}
      />,
    );
    expect(screen.getByRole("button", { name: "Enviar mensaje" })).toBeEnabled();
  });

  it("rechaza en el cliente formatos no soportados", async () => {
    const onUpload = vi.fn();
    render(<Composer onSend={vi.fn()} onStop={vi.fn()} streaming={false} onUpload={onUpload} />);
    const exe = new File(["MZ"], "programa.exe");
    await userEvent.upload(screen.getByTestId("file-input"), exe, { applyAccept: false });
    expect(onUpload).not.toHaveBeenCalled();
    expect(screen.getByRole("alert")).toHaveTextContent("Formato no soportado");
  });
});

function doc(id: string, filename: string, status: DocumentInfo["status"]): DocumentInfo {
  return {
    id,
    filename,
    kind: filename.split(".").pop() ?? "txt",
    mime_type: "text/plain",
    size_bytes: 10,
    status,
    error: null,
    chunk_count: 1,
    char_count: 10,
    created_at: "2026-01-01T00:00:00Z",
    updated_at: "2026-01-01T00:00:00Z",
  };
}

describe("validateUpload", () => {
  it("valida extensión, tamaño y vacío", () => {
    expect(validateUpload(new File(["x"], "a.pdf"))).toBeNull();
    expect(validateUpload(new File(["x"], "a.zip"))).toMatch(/Formato/);
    expect(validateUpload(new File([], "a.txt"))).toMatch(/vacío/);
  });
});
