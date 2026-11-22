# 04 — Diseño de la API

Base: `/api/v1`. JSON, errores en formato RFC 9457, paginación por cursor (`?cursor=…&limit=…` → `{items, next_cursor}`).

Autenticación: `Authorization: Bearer <access_token>`. En perfil local con Tauri, el token local de un solo uso se intercambia por una sesión al arrancar (ver seguridad).

Leyenda de permisos: 🔓 público · 👤 usuario autenticado · 🛡️ admin · 🏠 solo perfil local · 🌐 solo perfil servidor.

## Sistema

| Método | Ruta | Permiso | Descripción |
|--------|------|---------|-------------|
| GET | `/health` | 🔓 | Estado básico (`ok`) para *liveness* |
| GET | `/system/setup` | 🔓 | `{needs_setup, registration_open, profile}`: la interfaz decide si muestra "crear administrador" o el login |
| GET | `/system/info` | 👤 | Perfil (`local`/`server`), versión, estado de Ollama, Qdrant y BD |
| GET | `/system/capabilities` | 👤 | Funciones habilitadas: voz, sincronización, remoto, proveedores |

## Autenticación y sesiones

| Método | Ruta | Permiso | Descripción |
|--------|------|---------|-------------|
| POST | `/auth/register` | 🔓🌐 (si el registro está abierto) / 🛡️ | Crear cuenta |
| POST | `/auth/login` | 🔓 | `{email, password, device_name}` → `{access_token, expires_in}` + cookie `refresh` HttpOnly |
| POST | `/auth/refresh` | 🔓 (cookie) | Rotación del refresh token. Con cookie exige la cabecera `X-MILT-Client: web` (CSRF). Si se reutiliza uno ya rotado en los últimos 10 s con la sesión viva → `409 refresh_in_progress` (carrera entre pestañas); fuera de esa ventana se revoca toda la familia |
| POST | `/auth/logout` | 👤 | Revoca la sesión actual |
| POST | `/auth/local-exchange` | 🏠 | Intercambia el token de arranque de Tauri por una sesión |
| GET | `/auth/me` | 👤 | Usuario actual |
| PATCH | `/auth/me/password` | 👤 | Cambio de contraseña (revoca las demás sesiones) |
| GET | `/sessions` | 👤 | Sesiones y dispositivos activos |
| DELETE | `/sessions/{id}` | 👤 | Revocar una sesión |

## Usuarios (administración)

| Método | Ruta | Permiso |
|--------|------|---------|
| GET | `/users` | 🛡️ |
| POST | `/users` | 🛡️ |
| PATCH | `/users/{id}` | 🛡️ (rol, activo) |
| DELETE | `/users/{id}` | 🛡️ |

## Modelos

| Método | Ruta | Permiso | Descripción |
|--------|------|---------|-------------|
| GET | `/models` | 👤 | Modelos disponibles por proveedor: `{provider, name, size, family, capabilities:[chat,tools,embed,vision]}` |
| GET | `/models/{name}` | 👤 | Detalles (contexto máximo, cuantización) |
| POST | `/models/pull` | 🛡️🏠 | Descarga un modelo en Ollama (progreso por WS). **Pendiente: Fase 6** (asistente de primer arranque) |

## Conversaciones y mensajes

| Método | Ruta | Permiso | Descripción |
|--------|------|---------|-------------|
| GET | `/conversations` | 👤 | Lista paginada (`?q=`, `?archived=`) |
| POST | `/conversations` | 👤 | `{title?, model?, agent_profile?, params?}` |
| GET | `/conversations/{id}` | 👤 | Metadatos |
| PATCH | `/conversations/{id}` | 👤 | Título, fijada, archivada, modelo, parámetros |
| DELETE | `/conversations/{id}` | 👤 | Borrado lógico |
| GET | `/conversations/{id}/messages` | 👤 | Mensajes paginados |
| DELETE | `/conversations/{id}/messages/{mid}` | 👤 | Eliminar un mensaje |
| — | *(regenerar)* | 👤 | Se hace con el mensaje WS `chat.regenerate` o con `regenerate: true` en `POST /chat/completions`; no hay endpoint REST aparte |
| GET | `/conversations/{id}/export?format=md\|json` | 👤 | Exportar |
| GET | `/search/messages?q=` | 👤 | Búsqueda textual en el historial (Fase 2: `LIKE`; Fase 4: FTS5/`tsvector`) |

### Chat en streaming

**WebSocket** `GET /ws/chat` (preferido). Primer mensaje `{type:"auth", token}`: el token **no** se envía en la URL para que no aparezca en logs.

Cliente → servidor:

```jsonc
{ "type": "chat.send", "request_id": "uuid", "conversation_id": "uuid",
  "content": "texto", "attachments": ["document_id"],
  "model": "qwen3:8b", "params": { "temperature": 0.7 } }
{ "type": "chat.regenerate", "request_id": "uuid", "conversation_id": "uuid", "model"?: "...", "params"?: {} }
{ "type": "chat.cancel", "request_id": "uuid" }
{ "type": "auth", "token": "..." }   // renovar el token sin reconectar
{ "type": "tool.confirm", "call_id": "uuid", "approved": true }
{ "type": "ping" }
```

Servidor → cliente:

```jsonc
{ "type": "ready",         "user_id" }
{ "type": "chat.started",  "request_id", "conversation_id", "message_id", "user_message_id", "model", "context_dropped_messages" }
{ "type": "chat.delta",    "request_id", "text": "..." }
{ "type": "chat.thinking", "request_id", "text": "..." }   // solo si think=true
{ "type": "chat.context",  "request_id", "sources": [{ "kind": "memory|document", "id", "title", "locator" }] }
{ "type": "tool.call",     "request_id", "call_id", "tool", "arguments" }
{ "type": "tool.confirm_request", "request_id", "call_id", "tool", "summary", "risk_level", "expires_in": 120 }
{ "type": "tool.result",   "request_id", "call_id", "status": "ok|error|denied" }
{ "type": "chat.done",     "request_id", "message_id", "usage": { "prompt_tokens", "completion_tokens", "latency_ms", "first_token_ms" } }
{ "type": "chat.error",    "request_id", "code": "provider_unavailable|model_not_found|context_overflow|cancelled|not_found|validation_error|busy", "detail" }
{ "type": "error",         "code": "unauthorized|token_expired|invalid_message|frame_too_large|busy|not_found", "detail", "request_id"? }
{ "type": "pong" }
```

**Fallback SSE:** `POST /chat/completions` con el mismo cuerpo que `chat.send` devuelve `text/event-stream` con los mismos eventos. La cancelación se hace con `POST /chat/{request_id}/cancel`. Sin herramientas sensibles: solo las de lectura, porque SSE no permite confirmar en mitad del turno.

## Memoria

| Método | Ruta | Permiso | Descripción |
|--------|------|---------|-------------|
| GET | `/memories` | 👤 | Lista (`?kind=`, `?q=`) |
| POST | `/memories` | 👤 | Crear un recuerdo manual |
| PATCH | `/memories/{id}` | 👤 | Editar (reindexa el vector) |
| DELETE | `/memories/{id}` | 👤 | Eliminar (SQL + vector) |
| POST | `/memories/search` | 👤 | `{query, top_k}` → búsqueda semántica |
| GET | `/memories/suggestions` | 👤 | Recuerdos propuestos por el extractor, pendientes de aprobar |
| POST | `/memories/suggestions/{id}/accept` / `reject` | 👤 | — |
| DELETE | `/memories` | 👤 | Borrar toda la memoria (requiere `{confirm:"DELETE"}`) |
| GET | `/memories/export` | 👤 | Exportar mis datos (portabilidad) |

## Documentos (RAG)

| Método | Ruta | Permiso | Descripción |
|--------|------|---------|-------------|
| POST | `/documents` | 👤 | `multipart` → `202 {id, status:"pending"}` |
| GET | `/documents` | 👤 | Lista y estado |
| GET | `/documents/{id}` | 👤 | Metadatos, número de fragmentos y error |
| DELETE | `/documents/{id}` | 👤 | Borra el archivo, los fragmentos y los vectores |
| POST | `/documents/{id}/reindex` | 👤 | Volver a procesar |
| POST | `/documents/search` | 👤 | `{query, document_ids?, top_k}` → fragmentos con cita |
| POST | `/documents/{id}/summary` | 👤 | Resumen (stream por WS o respuesta completa) |

## Herramientas y automatización

| Método | Ruta | Permiso | Descripción |
|--------|------|---------|-------------|
| GET | `/tools` | 👤 | Catálogo: nombre, descripción, esquema y `risk_level` |
| GET | `/tools/policies` | 👤 | Política efectiva (auto / confirmar / denegada) |
| PUT | `/tools/policies/{tool}` | 👤🏠 | Cambiar la política. No se puede pasar de "confirmar" a "auto" para el riesgo `execute` |
| GET | `/tools/executions` | 👤 | Historial de ejecuciones |
| GET | `/automation/scripts` | 👤🏠 | Scripts de la lista blanca |
| POST | `/automation/scripts` | 🛡️🏠 | Registrar un script (ruta, hash SHA-256 y argumentos permitidos) |
| GET/POST | `/automation/workflows` | 👤 | Flujos de trabajo |
| POST | `/automation/workflows/{id}/run` | 👤 | Ejecutar un flujo (con confirmaciones) |

## Ciberseguridad

| Método | Ruta | Permiso | Descripción |
|--------|------|---------|-------------|
| POST | `/security/logs/analyze` | 👤 | Subida o ruta autorizada → hallazgos |
| POST | `/security/network/diagnose` | 👤🏠 | Diagnóstico **del propio equipo y su red local** |
| POST | `/security/ioc/match` | 👤 | Coincidencia de IoC (hash, IP, dominio) contra datos locales |
| GET | `/security/reports` · `/security/reports/{id}` | 👤 | Reportes (Markdown o PDF) |

## Voz

| Método | Ruta | Permiso | Descripción |
|--------|------|---------|-------------|
| POST | `/voice/transcribe` | 👤 | Audio (webm/wav) → texto |
| POST | `/voice/synthesize` | 👤 | `{text, voice}` → `audio/wav` |
| GET | `/voice/voices` | 👤 | Voces TTS disponibles |
| WS | `/ws/voice` | 👤 | (Fase futura) streaming de audio para manos libres |

## Ajustes

| Método | Ruta | Permiso |
|--------|------|---------|
| GET / PATCH | `/settings` | 👤 |
| GET / PUT | `/settings/allowed-roots` | 👤🏠 |

## Sincronización y acceso remoto

| Método | Ruta | Permiso | Descripción |
|--------|------|---------|-------------|
| POST | `/sync/push` | 👤🌐 | `{device_id, changes:[{entity, id, op, version, hlc, payload}]}` → `{accepted, conflicts}` |
| GET | `/sync/pull?since=<seq>&limit=` | 👤🌐 | Cambios posteriores a `seq` → `{changes, next_seq, has_more}` |
| GET | `/sync/status` | 👤🏠 | Estado de la sincronización local (pendientes, último sync, errores) |
| POST | `/sync/enable` · `/sync/disable` | 👤🏠 | Activar o desactivar la sincronización |
| POST | `/remote/enable` · `/remote/disable` | 👤🏠 | Túnel de acceso remoto (desactivado por defecto) |
| WS | `/relay/connect` | dispositivo 🌐 | Extremo del túnel saliente del equipo local |

## Auditoría

| Método | Ruta | Permiso |
|--------|------|---------|
| GET | `/audit?action=&from=&to=` | 👤 (los propios) / 🛡️ (todos) |
