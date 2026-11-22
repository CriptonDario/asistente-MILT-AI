import { render, screen } from "@testing-library/react";
import { describe, expect, it } from "vitest";
import { Markdown } from "./Markdown";

describe("Markdown", () => {
  it("renderiza bloques de código con lenguaje y botón de copiar", () => {
    const { container } = render(<Markdown text={"```python\nprint('hola')\n```"} />);
    expect(screen.getByText("python")).toBeInTheDocument();
    expect(screen.getByRole("button", { name: "Copiar código" })).toBeInTheDocument();
    expect(container.querySelector("code.hljs")).not.toBeNull();
  });

  it("no inserta HTML crudo de la respuesta del modelo", () => {
    const { container } = render(
      <Markdown text={'Hola <script>alert(1)</script><img src=x onerror="alert(1)">'} />,
    );
    expect(container.querySelector("script")).toBeNull();
    expect(container.querySelector("img")).toBeNull();
  });

  it("neutraliza enlaces javascript: y abre los externos en otra pestaña", () => {
    render(<Markdown text={"[malo](javascript:alert(1)) y [bueno](https://example.com)"} />);
    const bad = screen.getByText("malo").closest("a");
    expect(bad?.getAttribute("href") ?? "").not.toContain("javascript");
    const good = screen.getByText("bueno").closest("a");
    expect(good).toHaveAttribute("target", "_blank");
    expect(good).toHaveAttribute("rel", "noopener noreferrer");
  });

  it("soporta tablas GFM", () => {
    const { container } = render(<Markdown text={"| a | b |\n|---|---|\n| 1 | 2 |"} />);
    expect(container.querySelector("table")).not.toBeNull();
  });
});
