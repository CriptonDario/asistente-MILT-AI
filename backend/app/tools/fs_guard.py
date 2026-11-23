"""Acceso a archivos restringido a las carpetas que el usuario autoriza.

Defensas: rutas resueltas con ``resolve(strict)`` (sigue symlinks y *junctions*), deben
quedar dentro de una raíz permitida, sin rutas UNC ni *Alternate Data Streams*, con una
lista fija de nombres sensibles y sin acceso a la carpeta de datos de MILT (secretos, BD).
"""

from __future__ import annotations

import os
import re
import sys
from collections.abc import Iterable
from pathlib import Path

from app.tools.base import ToolError

#: Nombres de archivo o carpeta que nunca se leen ni se escriben.
SENSITIVE_NAMES = frozenset(
    {
        ".ssh",
        ".gnupg",
        ".aws",
        ".azure",
        ".kube",
        ".docker",
        ".git-credentials",
        ".netrc",
        ".pgpass",
        "id_rsa",
        "id_ed25519",
        "id_ecdsa",
        "known_hosts",
        "credentials.json",
        "secrets.json",
        "login data",
        "cookies",
        "web data",
        "key4.db",
        "logins.json",
        "ntuser.dat",
    }
)
# Los archivos del registro de Windows (SAM, SYSTEM, SECURITY) quedan cubiertos al
# vetar toda la carpeta de Windows; aquí no se listan para no bloquear carpetas de
# proyectos legítimas como app/security o modules/system.
SENSITIVE_SUFFIXES = (".pem", ".key", ".pfx", ".p12", ".kdbx", ".ppk", ".jks")
_ENV_NAME = re.compile(r"^\.env(\..*)?$", re.IGNORECASE)


def _forbidden_system_dirs() -> list[Path]:
    dirs: list[Path] = []
    if sys.platform == "win32":
        windir = os.environ.get("WINDIR") or os.environ.get("SYSTEMROOT")
        if windir:
            dirs.append(Path(windir))
    else:
        dirs += [Path("/etc"), Path("/proc"), Path("/sys"), Path("/dev"), Path("/boot")]
    return dirs


def _is_within(path: Path, root: Path) -> bool:
    try:
        path.relative_to(root)
    except ValueError:
        return False
    return True


def check_sensitive(path: Path) -> None:
    for part in path.parts:
        lowered = part.lower()
        if lowered in SENSITIVE_NAMES or _ENV_NAME.match(part):
            raise ToolError(f"Acceso denegado: «{part}» es un archivo o carpeta sensible.")
    if path.suffix.lower() in SENSITIVE_SUFFIXES:
        raise ToolError("Acceso denegado: los archivos de claves y certificados están protegidos.")


def validate_root(raw: str, *, data_dir: Path) -> Path:
    """Valida una carpeta que el usuario quiere autorizar."""
    if not raw or "\x00" in raw:
        raise ToolError("Ruta vacía o no válida.")
    if raw.startswith(("\\\\", "//")):
        raise ToolError("No se admiten rutas de red (UNC).")
    path = Path(raw).expanduser()
    if not path.is_absolute():
        raise ToolError("La carpeta debe indicarse con una ruta absoluta.")
    try:
        resolved = path.resolve(strict=True)
    except (FileNotFoundError, OSError) as exc:
        raise ToolError(f"La carpeta no existe: {raw}") from exc
    if not resolved.is_dir():
        raise ToolError(f"No es una carpeta: {raw}")
    if resolved.parent == resolved:
        raise ToolError("No se puede autorizar la raíz de una unidad completa.")
    if resolved == Path.home().resolve():
        raise ToolError("Autoriza una subcarpeta concreta, no tu carpeta personal completa.")
    for forbidden in [*_forbidden_system_dirs(), data_dir.resolve()]:
        if _is_within(resolved, forbidden) or _is_within(forbidden, resolved):
            raise ToolError("Esa carpeta contiene archivos del sistema o de MILT y no se permite.")
    check_sensitive(resolved)
    return resolved


class FsGuard:
    def __init__(self, roots: Iterable[Path], *, data_dir: Path) -> None:
        self.roots = [r.resolve() for r in roots]
        self.data_dir = data_dir.resolve()

    def require_roots(self) -> None:
        if not self.roots:
            raise ToolError(
                "No hay carpetas autorizadas. Añade alguna en el panel Herramientas → "
                "Carpetas permitidas."
            )

    def resolve(self, raw: str, *, must_exist: bool = True) -> Path:
        """Ruta real dentro de una carpeta permitida, o ``ToolError``."""
        self.require_roots()
        if not raw or "\x00" in raw:
            raise ToolError("Ruta vacía o no válida.")
        if raw.startswith(("\\\\", "//")):
            raise ToolError("No se admiten rutas de red (UNC).")
        # Alternate Data Streams (archivo.txt:oculto): ':' fuera de la letra de unidad.
        if ":" in raw[2:]:
            raise ToolError("Ruta no válida.")
        path = Path(raw).expanduser()
        if not path.is_absolute():
            path = self.roots[0] / path
        try:
            resolved = path.resolve(strict=must_exist)
        except FileNotFoundError as exc:
            raise ToolError(f"No existe: {raw}") from exc
        except OSError as exc:
            raise ToolError(f"Ruta no accesible: {raw}") from exc
        if not any(_is_within(resolved, root) for root in self.roots):
            raise ToolError(
                "Acceso denegado: la ruta está fuera de las carpetas autorizadas "
                f"({', '.join(str(r) for r in self.roots)})."
            )
        if _is_within(resolved, self.data_dir):
            raise ToolError("Acceso denegado: carpeta interna de MILT.")
        check_sensitive(resolved)
        return resolved

    def display(self, path: Path) -> str:
        """Ruta relativa a su raíz (más corta para el modelo y la interfaz)."""
        for root in self.roots:
            if _is_within(path, root):
                rel = path.relative_to(root)
                return f"{root.name}/{rel.as_posix()}" if str(rel) != "." else root.name
        return str(path)
