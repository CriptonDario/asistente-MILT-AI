# 02 — Estructura de directorios

## Mejora respecto a la propuesta inicial

La propuesta original organizaba el backend **por capas** (`api/`, `models/`, `schemas/`, `services/`…). Con 8 módulos de dominio, esa organización dispersa cada funcionalidad en 5 carpetas y facilita el acoplamiento. Se adopta una organización **por módulo de dominio** (*vertical slices*) con un núcleo compartido:

- `app/core/`: infraestructura transversal (configuración, logs, errores, seguridad base).
- `app/modules/<dominio>/`: todo lo de un dominio junto. Un módulo solo usa el **servicio** de otro, nunca su repositorio ni sus tablas.
- `app/llm/`, `app/vector/` y `app/tools/`: adaptadores de infraestructura detrás de protocolos.

Además se añade `packages/shared-types` para que backend y frontend compartan contratos generados.

## Árbol completo

```text
milt-ai/
├── backend/
│   ├── pyproject.toml              # dependencias (uv), ruff, mypy, pytest
│   ├── uv.lock
│   ├── alembic.ini
│   ├── migrations/
│   │   ├── env.py                  # async + render_as_batch para SQLite
│   │   └── versions/
│   ├── app/
│   │   ├── main.py                 # create_app(): routers, middlewares, lifespan
│   │   ├── core/
│   │   │   ├── config.py           # Settings (pydantic-settings), perfiles local/server
│   │   │   ├── logging.py          # structlog JSON + correlación por request_id
│   │   │   ├── errors.py           # jerarquía de excepciones → respuestas RFC 9457
│   │   │   ├── deps.py             # dependencias FastAPI (db, usuario actual, permisos)
│   │   │   ├── middleware.py       # request-id, cabeceras de seguridad, límite de tamaño
│   │   │   ├── rate_limit.py
│   │   │   └── ids.py              # UUIDv7
│   │   ├── db/
│   │   │   ├── base.py             # DeclarativeBase, mixins (timestamps, sync, soft-delete)
│   │   │   ├── session.py          # engine async, PRAGMAs de SQLite (WAL, foreign_keys)
│   │   │   └── types.py            # tipos portables (GUID, JSON) SQLite/PostgreSQL
│   │   ├── security/
│   │   │   ├── passwords.py        # Argon2id (argon2-cffi)
│   │   │   ├── tokens.py           # JWT acceso + refresh rotativo
│   │   │   ├── rbac.py             # roles → permisos, require_permission()
│   │   │   ├── secrets_store.py    # llavero del SO (keyring) / variables de entorno
│   │   │   └── crypto.py           # cifrado de campos y de la carga de sincronización
│   │   ├── llm/
│   │   │   ├── base.py             # LLMProvider, ChatChunk, GenerationParams
│   │   │   ├── ollama_provider.py
│   │   │   ├── registry.py         # selección de proveedor/modelo
│   │   │   └── tokens.py           # estimación de tokens para recortar contexto
│   │   ├── vector/
│   │   │   ├── base.py             # protocolo VectorStore
│   │   │   └── qdrant_store.py     # embebido o servidor según configuración
│   │   ├── tools/
│   │   │   ├── base.py             # Tool, ToolSpec, RiskLevel, ToolContext
│   │   │   ├── registry.py
│   │   │   ├── policy.py           # PermissionPolicy (permitir / confirmar / denegar)
│   │   │   ├── sandbox.py          # subprocess sin shell, timeouts, límites, entorno limpio
│   │   │   ├── fs_guard.py         # raíces permitidas, anti path traversal y symlinks
│   │   │   └── builtin/
│   │   │       ├── files.py        # file.read, file.list, project.tree
│   │   │       ├── code.py         # code.search, code.analyze
│   │   │       ├── documents.py    # doc.search, doc.summarize
│   │   │       ├── scripts.py      # script.run (solo lista blanca)
│   │   │       └── security.py     # logs.analyze, net.diagnose, ioc.match
│   │   ├── agents/
│   │   │   ├── orchestrator.py     # bucle LLM ↔ herramientas
│   │   │   ├── profiles.py         # general, coder, security, documents
│   │   │   └── prompts/            # prompts de sistema versionados (.md)
│   │   ├── modules/
│   │   │   ├── auth/               # router, service, schemas
│   │   │   ├── users/              # models, repository, service, router, schemas
│   │   │   ├── conversations/
│   │   │   ├── chat/               # ws.py (WebSocket), sse.py, context_builder.py
│   │   │   ├── memory/
│   │   │   ├── documents/          # ingestion.py, parsers/, chunking.py, retriever.py
│   │   │   ├── automation/         # workflows, tool_executions
│   │   │   ├── cybersecurity/      # reports
│   │   │   ├── voice/
│   │   │   ├── settings/           # preferencias por usuario
│   │   │   ├── models_catalog/     # /models
│   │   │   ├── sync/               # client.py (local), service.py (servidor)
│   │   │   ├── remote/             # túnel saliente al relay
│   │   │   ├── audit/
│   │   │   └── system/             # health, info, modo
│   │   └── workers/
│   │       └── tasks.py            # tareas en segundo plano (ingesta, embeddings)
│   └── tests/
│       ├── conftest.py             # app de prueba, BD en memoria, FakeLLMProvider
│       ├── unit/
│       ├── integration/
│       └── security/               # path traversal, authz, inyección, rate limit
├── frontend/
│   ├── package.json
│   ├── vite.config.ts
│   ├── tsconfig.json
│   ├── index.html
│   ├── public/                     # logotipo, favicon, fuentes autoalojadas
│   └── src/
│       ├── main.tsx
│       ├── app/                    # App.tsx, router.tsx, providers.tsx
│       ├── styles/                 # tokens.css (tema), globals.css
│       ├── components/
│       │   ├── ui/                 # Button, Input, Dialog, Tooltip, Badge, Switch…
│       │   ├── layout/             # Sidebar, Header, SidePanel
│       │   ├── chat/               # MessageList, Message, Composer, StreamingCursor, ToolConfirm
│       │   ├── memory/
│       │   ├── documents/
│       │   └── settings/
│       ├── pages/                  # ChatPage, LoginPage, SettingsPage, MemoryPage
│       ├── hooks/                  # useChatSocket, useModels, useVoice, useTheme
│       ├── services/               # apiClient.ts (fetch + refresh), ws.ts, endpoints
│       ├── stores/                 # zustand: ui, session, chat
│       ├── types/
│       │   └── api.gen.ts          # generado con openapi-typescript (no editar)
│       └── lib/                    # utilidades (formato, markdown)
├── desktop/
│   └── src-tauri/
│       ├── Cargo.toml
│       ├── tauri.conf.json         # CSP, sidecar, permisos (capabilities)
│       ├── capabilities/default.json
│       ├── binaries/               # milt-backend-<target-triple>.exe (generado)
│       └── src/main.rs             # lanza el sidecar, genera el token local, se lo pasa al WebView
├── infrastructure/
│   ├── docker/
│   │   ├── backend.Dockerfile      # multi-stage, usuario no root
│   │   └── frontend.Dockerfile     # build estático servido por Caddy
│   ├── caddy/Caddyfile
│   ├── compose/
│   │   ├── docker-compose.dev.yml  # postgres + qdrant para desarrollo
│   │   └── docker-compose.prod.yml
│   └── postgres/init.sql
├── scripts/
│   ├── dev.ps1                     # arranque de desarrollo en Windows
│   ├── dev.sh
│   ├── gen-types.ps1               # OpenAPI → TypeScript
│   └── build-desktop.ps1           # PyInstaller + tauri build
├── docs/
│   ├── README.md
│   ├── fase-1/
│   └── adr/                        # Architecture Decision Records
├── .env.example
├── .gitignore
├── .editorconfig
├── docker-compose.yml              # incluye infrastructure/compose/*
└── README.md
```

## Convenciones

- **Identificadores:** UUIDv7 (ordenables por tiempo), generados en el cliente o en el backend local. Son imprescindibles para la sincronización sin colisiones.
- **Fechas:** UTC, ISO-8601 y `timezone=True` en SQLAlchemy.
- **Errores:** formato *Problem Details* (RFC 9457): `{type, title, status, detail, instance, errors?}`.
- **API versionada:** prefijo `/api/v1`.
- **Datos de usuario en local:** `%APPDATA%\MILT\` en Windows (BD, vectores, adjuntos y logs), nunca dentro del directorio del código.
