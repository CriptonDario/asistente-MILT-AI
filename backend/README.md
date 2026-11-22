# MILT AI: backend

API FastAPI local-first: autenticación, conversaciones y chat con streaming sobre Ollama.

## Requisitos

- [uv](https://docs.astral.sh/uv/) (instala y gestiona Python 3.12 para el proyecto)
- [Ollama](https://ollama.com) con al menos un modelo: `ollama pull qwen3:1.7b`

## Puesta en marcha

```powershell
cd backend
uv sync                                   # crea .venv con Python 3.12 e instala dependencias
uv run uvicorn app.main:app --host 127.0.0.1 --port 8765 --reload
```

O desde la raíz del repositorio: `.\scripts\dev.ps1`.

- Documentación interactiva: <http://127.0.0.1:8765/docs> (desactivada con `MILT_ENV=production`)
- Las migraciones se aplican solas al arrancar (`MILT_AUTO_MIGRATE=true`).
- Los datos se guardan en `%APPDATA%\MILT\` (BD `milt.db`, `secrets/jwt.key`).
- **La primera cuenta registrada es la administradora.** Después, el registro público queda cerrado salvo con `MILT_ALLOW_REGISTRATION=true`.
- Sin Ollama, `MILT_LLM_PROVIDER=fake` devuelve respuestas simuladas.

## Calidad

```powershell
uv run pytest                       # 84 pruebas (unitarias + integración)
$env:MILT_TEST_OLLAMA=1; uv run pytest -m ollama   # prueba contra Ollama real
uv run ruff check .                 # lint (incluye reglas de seguridad de bandit)
uv run ruff format .                # formato
uv run mypy app                     # tipado estricto
```

## Migraciones

```powershell
uv run alembic revision --autogenerate -m "descripción"   # revisar SIEMPRE el archivo generado
uv run alembic upgrade head
```

La prueba `tests/integration/test_migrations.py` falla si un modelo cambia sin su migración.

## Estructura

```text
app/
├── main.py              create_app(): middlewares, routers, ciclo de vida
├── core/                config, errores RFC 9457, logging, middlewares, ids (UUIDv7), HLC
├── db/                  motor async, tipos portables SQLite/PostgreSQL, migraciones
├── security/            Argon2id, JWT, refresh tokens, RBAC, secretos
├── llm/                 LLMProvider, OllamaProvider, FakeLLMProvider
├── agents/              perfiles y prompts de sistema
└── modules/             auth, users, settings, conversations, chat (ws/sse), models_catalog,
                         audit, system
```
