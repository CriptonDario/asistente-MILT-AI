# 06 — Estrategia de seguridad

## 1. Modelo de amenazas (resumen)

| Activo | Amenaza | Mitigación principal |
|--------|---------|----------------------|
| Archivos y equipo local | El modelo, manipulado por **inyección de prompt** desde un documento o una web, intenta leer, escribir o ejecutar algo | Herramientas con permisos, `fs_guard`, confirmación humana, salidas de herramientas tratadas como datos |
| Backend local en `127.0.0.1` | Otra web abierta en el navegador ataca `localhost` (CSRF o DNS rebinding) | Validación de la cabecera `Host`, CORS estricto, token local obligatorio y sin cookies en el perfil local |
| Cuentas web | Fuerza bruta, *credential stuffing*, robo de token | Argon2id, rate limit, bloqueo progresivo, access token de 15 min y refresh rotativo con detección de reutilización |
| Datos de un usuario | Acceso de otro usuario (IDOR) | Filtro `user_id` obligatorio en los repositorios y en el `VectorStore`, con pruebas de autorización por endpoint |
| Archivos subidos | Archivos maliciosos, *zip bombs*, *path traversal* | Límite de tamaño, MIME real, nombre UUID, parsers sin macros, límites de páginas y celdas |
| Secretos | Fuga por logs o repositorio | `.env` fuera de Git, keyring del SO, redacción en logs, `detect-secrets` en *pre-commit* |
| Sincronización | Lectura en el servidor | TLS 1.3 + cifrado E2E opcional |

## 2. Autenticación

- **Contraseñas:** Argon2id (`argon2-cffi`, `PasswordHasher` con parámetros ajustados para unos 50–100 ms en el servidor: `time_cost=3`, `memory_cost=64 MiB`, `parallelism=2`, ajustables en `.env`). `check_needs_rehash` actualiza los hashes antiguos al iniciar sesión.
- Política: mínimo 12 caracteres, comprobación contra una lista local de contraseñas comunes y sin reglas de composición arbitrarias (NIST SP 800-63B).
- **Tokens:**
  - *Access* JWT de 15 min con `sub`, `role`, `sid`, `exp`, `iat`, `jti`, `aud`, `iss`. Algoritmo fijado en la verificación (sin aceptar `alg: none`).
  - *Refresh* opaco (256 bits aleatorios) de 30 días, guardado como **hash SHA-256**, rotado en cada uso. Si se reutiliza uno ya rotado, se revoca toda su familia.
  - En web: refresh en cookie `HttpOnly; Secure; SameSite=Strict; Path=/api/v1/auth`. El access token se mantiene **solo en memoria** en el frontend, nunca en `localStorage`.
- **CSRF del refresh por cookie:** `/auth/refresh` con cookie exige la cabecera `X-MILT-Client: web`. Una cabecera propia obliga al navegador a hacer *preflight* CORS, que falla para cualquier origen no autorizado. Es necesario porque, para `SameSite`, otras webs en `localhost:<otro puerto>` cuentan como el mismo sitio.
- **Rotación atómica:** el refresh se consume con un `UPDATE … WHERE revoked_at IS NULL` (solo gana una petición concurrente). Una reutilización dentro de los 10 s siguientes, con la sesión todavía viva, devuelve 409 en lugar de revocar la sesión.
- **Contador de fallos atómico** (`failed_logins = failed_logins + 1`) y el **cambio de contraseña** también tiene límite de intentos y cuenta para el bloqueo.
- **Perfil local (Tauri):** al arrancar, Tauri genera un **token aleatorio de un solo uso** (el backend lo marca como consumido en el primer canje), lo pasa al sidecar por variable de entorno y al WebView por IPC. El frontend lo intercambia en `/auth/local-exchange`. Ningún otro proceso o web lo conoce. En modo local de desarrollo (sin Tauri) se exige un login normal.
- **Fuerza bruta:** rate limit por IP y por cuenta (5 intentos/min) y bloqueo progresivo (`locked_until`). Mensajes de error genéricos para no revelar qué cuentas existen.
- **2FA (TOTP):** previsto en Fase 7 para el perfil servidor y el acceso remoto.

## 3. Autorización (RBAC + propiedad)

- Roles: `admin` y `user`. Los permisos se definen en código (`rbac.py`), por ejemplo `users:manage`, `models:pull`, `scripts:register`, `audit:read_all`.
- Dependencia `require_permission("...")` en cada endpoint, más una **comprobación de propiedad** en el repositorio: todas las consultas incluyen `user_id = current_user.id`. Si el recurso es de otro usuario se devuelve 404, no 403, para no confirmar que existe.
- Pruebas automáticas: un test parametrizado recorre **todas** las rutas del OpenAPI y verifica que sin token devuelven 401 (salvo la lista explícita de rutas públicas).

## 4. Seguridad de herramientas y ejecución (núcleo crítico)

**Principio: el LLM propone, la política decide y el usuario confirma.**

| Nivel de riesgo | Ejemplos | Política por defecto (local) | Sesión remota |
|-----------------|----------|-------------------------------|---------------|
| `read` | `file.read`, `project.tree`, `doc.search`, `logs.analyze` | Automática, **dentro de las raíces permitidas** | Automática |
| `write` | Crear o modificar archivos, guardar reportes | **Confirmar** | Denegada |
| `execute` | `script.run`, flujos con scripts | **Confirmar siempre** (no se puede cambiar a automática) | Denegada |
| `network` | `net.diagnose` (red propia) | Confirmar | Denegada |

Controles:

1. **Sin comandos arbitrarios.** No existe ninguna herramienta "shell". `script.run` solo ejecuta scripts **registrados** por un admin en local, identificados por ruta absoluta + **hash SHA-256** (si el archivo cambia, se bloquea) y con argumentos validados contra un esquema.
2. **Ejecución:** `subprocess` con lista de argumentos (`shell=False`), entorno mínimo (sin variables con secretos), directorio de trabajo controlado, `timeout` (30 s por defecto), límite de salida (1 MB) y terminación del árbol de procesos. En Windows se usa un **Job Object** con límite de memoria y `KILL_ON_JOB_CLOSE`. Como opción, se puede ejecutar dentro de un contenedor Docker desechable sin red.
3. **`fs_guard`:** las rutas se resuelven con `Path.resolve(strict=True)` y deben quedar dentro de `allowed_roots`. Se rechazan los symlinks y *junctions* que salgan de la raíz, y en Windows también los *Alternate Data Streams* (`:`) y las rutas UNC. Lista de denegación fija: `.ssh`, `.env`, almacenes de credenciales del navegador, `C:\Windows\System32\config`, etc.
4. **Validación de argumentos** con Pydantic (`extra="forbid"`) antes de ejecutar. Si es inválido, se devuelve un error al modelo y no se ejecuta nada.
5. **Confirmación:** la interfaz muestra la herramienta, los argumentos **reales** (no el resumen del modelo) y el nivel de riesgo. Expira en 120 s (= denegada).
6. **Límites del agente:** máximo 8 llamadas a herramientas por turno y presupuesto de tiempo total.
7. **Defensa ante inyección de prompt:** el contenido de documentos y de resultados de herramientas se envuelve como *datos no confiables* y el prompt de sistema indica no obedecer instrucciones que vengan de ahí. Además, ninguna acción sensible se ejecuta sin confirmación, **aunque el modelo sea engañado**. La seguridad no depende de que el modelo "se porte bien".
8. **Ciberseguridad responsable:** las herramientas de red se limitan al **propio equipo y a la red local configurada por el usuario** (rangos privados RFC 1918 declarados en ajustes), sin escaneo de terceros.

## 5. Validación de entradas e inyección

- **SQL:** solo ORM y consultas parametrizadas de SQLAlchemy, nunca concatenación de texto. Las consultas FTS se escapan mediante el repositorio.
- **Pydantic** en todas las entradas, con límites de longitud (mensaje ≤ 32 k caracteres, título ≤ 200).
- **Subidas:** como máximo 50 MB (configurable), MIME detectado por contenido, extensión en lista blanca, nombre en disco = UUID, y sin macros (DOCX/XLSX se leen como datos con `openpyxl` `read_only=True` y `data_only=True`). Límites de páginas, filas y fragmentos contra bombas de descompresión.
- **Salida en el frontend:** el Markdown se renderiza **sin HTML crudo** (`react-markdown` sin `rehype-raw`). Los enlaces llevan `rel="noopener noreferrer"`. Nada de `dangerouslySetInnerHTML`.

## 6. Comunicaciones y cabeceras

- **Servidor:** HTTPS obligatorio (Caddy con TLS 1.2+ y preferencia por 1.3), HSTS, redirección de 80 a 443 y WSS.
- **Local:** el backend escucha **solo en `127.0.0.1`**. Se valida que `Host` sea `127.0.0.1:<puerto>` o `localhost:<puerto>` (contra DNS rebinding). CORS permite únicamente el origen de Tauri (`http://tauri.localhost` / `tauri://localhost`) y el de Vite en desarrollo.
- Cabeceras: `Content-Security-Policy` (`default-src 'self'`; `connect-src` limitado al backend), `X-Content-Type-Options: nosniff`, `Referrer-Policy: no-referrer`, `frame-ancestors 'none'`.
- Tauri 2: *capabilities* mínimas (sin `shell:allow-execute` genérico). Solo se permite lanzar el sidecar `milt-backend`.

## 7. Secretos

- `.env` para desarrollo (en `.gitignore`) y `.env.example` sin valores reales.
- En el escritorio, la clave de firma JWT local y la credencial del dispositivo se guardan en el **Administrador de credenciales de Windows** mediante `keyring`.
- En el servidor, variables de entorno o *Docker secrets*. Rotación documentada.
- Logs con **redacción automática** (procesador de structlog) de `password`, `token`, `authorization` y `api_key`. El contenido de los mensajes **no** se registra salvo que se active el modo depuración local.

## 8. Auditoría

Se registran, como mínimo: login y logout (con éxito y fallidos), cambios de contraseña, creación o revocación de sesiones, **cada ejecución de herramienta** (decisión y resultado), cambios de política o de raíces permitidas, activación de sincronización o acceso remoto, borrados de memoria y acciones de admin.
Cada registro guarda `prev_hash` (hash encadenado), lo que permite detectar alteraciones del historial. `audit_log.user_id` **no tiene clave foránea** a propósito: un `ON DELETE SET NULL` reescribiría filas incluidas en el hash al borrar un usuario y rompería la cadena.

## 9. Pruebas de seguridad (Fase 8, y continuas desde la Fase 2)

- Tests de authz por endpoint, IDOR, *path traversal* (`..\`, symlinks, UNC, ADS), inyección SQL o FTS y límites de subida.
- `pip-audit` / `uv` audit, `pnpm audit`, `bandit` y `cargo audit` en CI.
- OWASP ZAP *baseline* contra el perfil servidor antes del despliegue.
