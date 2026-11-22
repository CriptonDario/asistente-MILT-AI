# 07 — Riesgos técnicos y plan de implementación

## 1. Estado del entorno detectado (22-11-2026)

| Herramienta | Estado | Acción |
|-------------|--------|--------|
| Hardware | Ryzen 7 3700U, **AMD Radeon Vega 10 integrada (2 GB compartidos)**, ~10 GB de RAM utilizable | **Inferencia en CPU.** Modelos de 3–4 B en Q4 (ver §4) |
| Python | 3.15.0 del sistema + **3.12.16 gestionado por uv** | ✅ El proyecto usa 3.12 |
| uv | 0.13.9 | ✅ Instalado |
| Node.js | 24 | ✅ Válido. Instalar `pnpm` (`corepack enable`) en la Fase 3 |
| Docker | 29.8 | ✅ Válido para PostgreSQL y Qdrant en desarrollo y para el perfil servidor |
| Ollama | 0.40.16 | ✅ Instalado y en ejecución en `127.0.0.1:11434` |
| Rust / rustup | **No instalado** | Necesario solo en la Fase 6 (Tauri). Requiere *Visual Studio Build Tools* (C++) y WebView2 |
| Git | 2.50 | ✅ Repositorio inicializado (rama `main`) |

## 2. Riesgos e incompatibilidades

| ID | Riesgo | Prob. | Impacto | Mitigación |
|----|--------|-------|---------|------------|
| R1 | **Python 3.15 sin *wheels*** para extensiones nativas (ctranslate2, qdrant/grpc, pydantic-core, argon2) → fallos de compilación en Windows | Alta | Alto | Fijar `requires-python = ">=3.12,<3.14"` y crear el entorno con `uv python install 3.12` |
| R2 | **Hardware insuficiente** para modelos de 7–8 B (VRAM < 6 GB) → respuestas lentas | Media | Alto | Catálogo dinámico, recomendar Q4 y modelos de 3–4 B como alternativa, ajustar `num_ctx`. Medir tokens/s en la Fase 2 |
| R3 | **Tool calling irregular** en modelos locales pequeños (JSON mal formado, herramientas inventadas) | Alta | Medio | Validar con Pydantic, reintentar con el mensaje de error, limitar iteraciones y desactivar herramientas por modelo si falla mucho. Usar el formato nativo `tools` de Ollama |
| R4 | **Inyección de prompt** desde documentos o logs analizados | Alta | Alto | Confirmación humana obligatoria en `write`/`execute`/`network`; la seguridad no depende del modelo (ver 06 §4) |
| R5 | **Diferencias SQLite ↔ PostgreSQL** (ALTER TABLE limitado, JSON, FTS, concurrencia) | Media | Medio | `render_as_batch`, tipos portables, FTS detrás de un repositorio y CI ejecutando tests contra **ambas** BD |
| R6 | **Concurrencia de escritura en SQLite** (stream + ingesta + sync) → `database is locked` | Media | Medio | WAL, `busy_timeout=5000`, transacciones cortas y una sola cola de tareas de escritura |
| R7 | **Qdrant embebido**: un solo proceso puede abrir la carpeta local (bloqueo de archivo) | Media | Medio | Un único `QdrantClient` por proceso (singleton en *lifespan*) y un único backend activo, controlado por Tauri |
| R8 | **Empaquetado Python como sidecar** (PyInstaller): tamaño grande (>150 MB con voz), falsos positivos de antivirus, imports ocultos | Alta | Medio | Voz como extra opcional, `--onedir` en vez de `--onefile`, firma de código del instalador y una prueba de humo del binario en CI |
| R9 | **Cambio de modelo de embeddings** invalida los vectores | Media | Medio | Colecciones con el nombre del modelo, reindexado en segundo plano y SQL como fuente de verdad |
| R10 | **Conflictos de sincronización** y deriva de relojes | Media | Medio | HLC, mensajes *append-only*, LWW por campo y una interfaz para resolver conflictos de memoria |
| R11 | **WebSocket detrás de proxies** o corporativos | Baja | Medio | Fallback SSE con el mismo contrato de eventos |
| R12 | **Ventana de contexto**: historial + memoria + RAG supera `num_ctx` | Alta | Medio | `ContextBuilder` con presupuesto por secciones (sistema 10 %, memoria 15 %, RAG 30 %, historial el resto), estimación de tokens y resumen de conversaciones largas |
| R13 | **Tauri 2 en Android** con el backend Python: Python no corre como sidecar en Android | Alta | Alto (Fase futura) | En Android, la app es **cliente** del perfil servidor o del equipo local por el relay. La IA local en el móvil queda fuera de alcance inicial (posible más adelante con llama.cpp nativo) |
| R14 | **Voz en Windows**: faster-whisper en CPU es lento con modelos grandes | Media | Bajo | Modelo `small`/`base` por defecto, GPU CUDA opcional y Web Speech API del navegador como alternativa en modo web |
| R15 | **Conflicto de puertos** con Laragon (80/443/3306) | Baja | Bajo | Backend en `8765` y Vite en `5173`. PostgreSQL en Docker mapeado a `5433` |
| R16 | **Alcance del proyecto** muy grande para un desarrollador | Alta | Alto | Fases con un **MVP vertical** al final de la Fase 3 (chat local completo) antes de ampliar |

## 3. Plan de implementación por fases

Cada fase termina con: código completo, pruebas en verde (`pytest`, `vitest`), lint y tipado sin errores, y documentación actualizada. **No se avanza con errores críticos abiertos.**

### Fase 2: Backend base (perfil local)
1. Inicializar el repositorio, `pyproject.toml` (uv, Python 3.12), ruff, mypy y pytest.
2. `core/`: configuración por perfil, logging estructurado, errores RFC 9457 y middlewares de seguridad (Host, CORS, cabeceras, límite de tamaño).
3. `db/`: engine async, PRAGMAs de SQLite, mixins, Alembic y migración inicial (`users`, `refresh_tokens`, `devices`, `conversations`, `messages`, `user_settings`, `audit_log`).
4. `security/`: Argon2id, JWT + refresh rotativo, RBAC.
5. Módulos `auth`, `users`, `conversations`, `audit` y `system`.
6. `llm/`: `LLMProvider`, `OllamaProvider` (streaming, health, list_models, manejo de desconexión) y `FakeLLMProvider` para tests.
7. `chat/`: WebSocket `/ws/chat` (auth en el primer mensaje, cancelación, persistencia) y fallback SSE.
8. Pruebas: unitarias (hash, tokens, ContextBuilder) e integración (auth, CRUD, chat con proveedor falso), además de authz de todas las rutas.

**Criterio de salida:** conversar con un modelo de Ollama vía WebSocket con streaming, historial persistido y autenticación.

### Fase 3: Frontend
Vite + React + TS + Tailwind 4, sistema de *tokens* de diseño (tema oscuro y claro), layout (sidebar, cabecera, paneles), `apiClient` con refresh, `useChatSocket` con streaming y cancelación, lista de conversaciones, selector de modelo, insignia local/web, estado de Ollama y render de Markdown y código. Tipos generados desde el OpenAPI. Tests con Vitest.
**Criterio de salida: MVP vertical utilizable.**

### Fase 4: Memoria y RAG
Qdrant embebido, `EmbeddingService`, módulo `memory` (CRUD, búsqueda y sugerencias con aprobación), ingesta de documentos (PDF, DOCX, XLSX, CSV, TXT), `Retriever` con citas, integración en `ContextBuilder` y panel de Memoria y Documentos en la interfaz.

### Fase 5: Herramientas
`ToolRegistry`, `PermissionPolicy`, `fs_guard`, `SandboxExecutor` (Job Objects en Windows), orquestador agente, confirmaciones en la interfaz, herramientas de programación, documentos, automatización (scripts de la lista blanca y flujos) y ciberseguridad (logs, IoC, diagnóstico de la red propia, reportes). Voz (STT y TTS) con botón de micrófono.

### Fase 6: Escritorio (Tauri 2)
Instalación de Rust, proyecto `desktop/`, sidecar PyInstaller, token local de arranque, supervisión del proceso (reinicio y cierre limpio), datos en `%APPDATA%\MILT`, asistente de primer arranque (detectar o instalar Ollama y descargar el modelo recomendado) e instalador MSI/NSIS.

### Fase 7: Plataforma web
Perfil servidor (PostgreSQL, Qdrant server), Docker Compose de producción, Caddy con HTTPS, registro y administración de usuarios, 2FA TOTP, sincronización (`change_log`, push/pull, outbox, HLC, E2E opcional), relay de acceso remoto y PWA instalable (base para Android).

### Fase 8: Pruebas y optimización
Cobertura ≥ 80 % en servicios críticos, E2E con Playwright, pruebas de seguridad (ZAP, bandit, auditorías de dependencias), perfilado (latencia del primer token, ingesta), CI en GitHub Actions y documentación final de usuario y operación.

## 4. Decisiones aprobadas y perfil de hardware

**Aprobado:** Python 3.12 gestionado por `uv` y Qdrant como almacén vectorial.

**Perfil "equipo modesto" (CPU, ~10 GB de RAM), configuración por defecto:**

| Uso | Modelo | Memoria aprox. | Nota |
|-----|--------|----------------|------|
| Chat general | `qwen3:4b` | ~2,5–3 GB | Buen español y *tool calling*. Esperable ~4–8 tokens/s en CPU |
| Alternativa más rápida | `llama3.2:3b` o `qwen3:1.7b` | ~1,5–2 GB | Para respuestas rápidas o equipos ocupados |
| Embeddings | `nomic-embed-text` (~0,3 GB) por defecto; `bge-m3` (~1,2 GB) opcional | — | Se evalúa la calidad en español en la Fase 4 |
| Contexto | `num_ctx = 4096` | — | Contextos mayores multiplican la RAM y la latencia |

Ajustes que esto implica:
- `OLLAMA_MAX_LOADED_MODELS=1` y `keep_alive` corto para no tener chat y embeddings cargados a la vez sin necesidad.
- Ingesta de documentos en **segundo plano y por lotes pequeños**, para no bloquear el chat.
- **Voz:** faster-whisper `base` con `int8` en CPU. Piper es ligero.
- R2 pasa a riesgo **confirmado**: el selector de modelo mostrará la velocidad medida (tokens/s) de cada modelo.
- La interfaz web del servidor (Fase 7) permitirá, opcionalmente, usar un proveedor externo o un servidor con GPU para tareas pesadas, sin afectar al modo local.

**Pendiente de confirmar más adelante:** Android como cliente (Fase 7+).
