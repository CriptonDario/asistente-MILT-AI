import { render, screen } from "@testing-library/react";
import { describe, expect, it } from "vitest";
import { Sources } from "./Sources";

describe("Sources", () => {
  it("muestra documentos citados con su número y ubicación, y los recuerdos usados", () => {
    render(
      <Sources
        sources={[
          { kind: "document", id: "c1", title: "orion.txt", ref: 1, location: "línea 3" },
          { kind: "memory", id: "m1", title: "El usuario programa con Laravel" },
        ]}
        warnings={["No se pudo consultar la memoria en este turno."]}
      />,
    );
    expect(screen.getByText("[1]")).toBeInTheDocument();
    expect(screen.getByText("orion.txt")).toBeInTheDocument();
    expect(screen.getByText("· línea 3")).toBeInTheDocument();
    expect(screen.getByText("El usuario programa con Laravel")).toBeInTheDocument();
    expect(screen.getByText(/No se pudo consultar la memoria/)).toBeInTheDocument();
  });

  it("no renderiza nada sin fuentes ni avisos", () => {
    const { container } = render(<Sources sources={[]} />);
    expect(container).toBeEmptyDOMElement();
  });
});
