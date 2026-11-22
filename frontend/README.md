# MILT AI: frontend

Interfaz web de MILT: React 19, TypeScript, Vite y Tailwind CSS 4.

## Puesta en marcha

```powershell
# desde la raíz: backend + interfaz
.\scripts\dev.ps1            # con Ollama
.\scripts\dev.ps1 -Fake      # sin Ollama (respuestas simuladas)
```

O solo la interfaz (con el backend ya arrancado en el puerto 8765):

```powershell
cd frontend
corepack pnpm install
corepack pnpm dev            # http://localhost:5173
```

En desarrollo, Vite hace de proxy de `/api` (HTTP y WebSocket) hacia `127.0.0.1:8765`. El navegador ve un único origen, así que la cookie del refresh token funciona sin CORS.

## Calidad

```powershell
corepack pnpm typecheck      # TypeScript estricto
corepack pnpm test           # Vitest + Testing Library
corepack pnpm build          # build de producción en dist/
```

## Contrato con el backend

Los tipos de `src/types/api.gen.ts` se generan desde el OpenAPI del backend. **No los edites a mano.** Tras cambiar la API:

```powershell
.\scripts\gen-types.ps1
```

## Estructura

```text
src/
├── app/          App (router y proveedores), queryClient
├── components/
│   ├── ui/       Button, IconButton, Modal, Spinner, Logo
│   ├── layout/   AppShell, Sidebar, ConversationItem, Header, SidePanel
│   ├── chat/     MessageList, MessageItem, StreamingMessage, Composer, Markdown, ModelSelector
│   ├── settings/ SettingsPanel (tema, modelo, sesiones, contraseña)
│   └── memory/   MemoryPanel (Fase 4)
├── hooks/        consultas (TanStack Query), useChat, useTheme, useAuthBootstrap
├── services/     http (refresh single-flight + Web Locks), chatSocket (WebSocket), endpoints
├── stores/       Zustand: sesión (token solo en memoria), chat (streams), ui
├── styles/       tokens de diseño (oscuro/claro) y estilos base
└── types/        api.gen.ts (generado) y alias legibles
```

## Seguridad en el cliente

- El access token vive **solo en memoria**. El refresh token va en una cookie HttpOnly que JavaScript no puede leer.
- La renovación de sesión es *single-flight* y se serializa entre pestañas con Web Locks, para que el backend no la tome por un robo de token.
- El Markdown de las respuestas se renderiza **sin HTML crudo**, y las URL `javascript:` se neutralizan.
- El token del WebSocket se envía en el primer mensaje, nunca en la URL.
