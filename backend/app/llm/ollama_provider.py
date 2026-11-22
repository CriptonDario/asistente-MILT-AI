"""Proveedor Ollama mediante su API REST (``/api/chat``, ``/api/tags``, ``/api/show``...)."""

from __future__ import annotations

import json
import time
import uuid
from collections.abc import AsyncIterator
from typing import Any

import httpx
import structlog

from app.llm.base import (
    ChatChunk,
    ChatMessage,
    Done,
    GenerationParams,
    InsufficientMemoryError,
    ModelInfo,
    ModelNotFoundError,
    ProviderError,
    ProviderHealth,
    ProviderUnavailableError,
    TextDelta,
    ThinkingDelta,
    ToolCallRequest,
    Usage,
)

log = structlog.get_logger(__name__)

_NS_PER_MS = 1_000_000
_OOM_MARKERS = ("out-of-memory", "out of memory", "failed to allocate", "insufficient memory")
_OOM_DETAIL = (
    "Ollama no tiene memoria RAM suficiente para cargar el modelo. Cierra programas "
    "(navegadores, Docker) o elige un modelo más pequeño."
)


def _provider_error(message: str) -> ProviderError:
    """Traduce los errores de Ollama más habituales a errores comprensibles."""
    lowered = message.lower()
    if any(marker in lowered for marker in _OOM_MARKERS):
        return InsufficientMemoryError(_OOM_DETAIL)
    return ProviderError(message)


class OllamaProvider:
    name = "ollama"

    def __init__(
        self,
        base_url: str,
        *,
        connect_timeout: float = 5.0,
        read_timeout: float = 600.0,
        default_think: bool = False,
        transport: httpx.AsyncBaseTransport | None = None,
    ) -> None:
        self._client = httpx.AsyncClient(
            base_url=base_url,
            timeout=httpx.Timeout(connect=connect_timeout, read=read_timeout, write=30.0, pool=5.0),
            transport=transport,
        )
        self._default_think = default_think
        self._model_cache: dict[str, ModelInfo] = {}

    # ------------------------------------------------------------------ utilidades
    @staticmethod
    def _error_message(response: httpx.Response) -> str:
        try:
            data = response.json()
            if isinstance(data, dict) and isinstance(data.get("error"), str):
                return str(data["error"])
        except ValueError:
            pass
        return f"HTTP {response.status_code}"

    async def _request_json(
        self, method: str, path: str, *, json_body: dict[str, Any] | None = None
    ) -> dict[str, Any]:
        try:
            response = await self._client.request(method, path, json=json_body)
        except (httpx.ConnectError, httpx.ConnectTimeout) as exc:
            raise ProviderUnavailableError(
                "No se puede conectar con Ollama. ¿Está en ejecución?"
            ) from exc
        except httpx.TimeoutException as exc:
            raise ProviderUnavailableError("Ollama no respondió a tiempo.") from exc
        except httpx.HTTPError as exc:
            raise ProviderError(f"Error de comunicación con Ollama: {type(exc).__name__}") from exc
        if response.status_code == 404:
            raise ModelNotFoundError(self._error_message(response))
        if response.status_code >= 400:
            raise _provider_error(self._error_message(response))
        try:
            data = response.json()
        except ValueError as exc:
            raise ProviderError("Respuesta no válida de Ollama.") from exc
        if not isinstance(data, dict):
            raise ProviderError("Respuesta no válida de Ollama.")
        return data

    @staticmethod
    def _to_ollama_message(message: ChatMessage) -> dict[str, Any]:
        out: dict[str, Any] = {"role": message.role, "content": message.content}
        if message.tool_calls:
            out["tool_calls"] = message.tool_calls
        return out

    @staticmethod
    def _options(params: GenerationParams) -> dict[str, Any]:
        options: dict[str, Any] = {}
        if params.temperature is not None:
            options["temperature"] = params.temperature
        if params.top_p is not None:
            options["top_p"] = params.top_p
        if params.num_ctx is not None:
            options["num_ctx"] = params.num_ctx
        if params.max_tokens is not None:
            options["num_predict"] = params.max_tokens
        if params.seed is not None:
            options["seed"] = params.seed
        return options

    # ------------------------------------------------------------------ API pública
    async def health(self) -> ProviderHealth:
        start = time.perf_counter()
        try:
            response = await self._client.get("/api/version", timeout=3.0)
            response.raise_for_status()
            version = response.json().get("version")
        except (httpx.HTTPError, ValueError) as exc:
            return ProviderHealth(ok=False, provider=self.name, detail=type(exc).__name__)
        return ProviderHealth(
            ok=True,
            provider=self.name,
            version=str(version) if version else None,
            latency_ms=round((time.perf_counter() - start) * 1000),
        )

    async def list_models(self) -> list[ModelInfo]:
        data = await self._request_json("GET", "/api/tags")
        result: list[ModelInfo] = []
        for raw in data.get("models") or []:
            name = raw.get("model") or raw.get("name")
            if not isinstance(name, str):
                continue
            try:
                result.append(await self.get_model(name, size_hint=raw.get("size")))
            except (ProviderError, ModelNotFoundError):
                details = raw.get("details") or {}
                result.append(
                    ModelInfo(
                        provider=self.name,
                        name=name,
                        size_bytes=raw.get("size"),
                        family=details.get("family"),
                        parameter_size=details.get("parameter_size"),
                        quantization=details.get("quantization_level"),
                    )
                )
        return result

    async def get_model(self, name: str, *, size_hint: int | None = None) -> ModelInfo:
        cached = self._model_cache.get(name)
        if cached is not None:
            return cached
        data = await self._request_json("POST", "/api/show", json_body={"model": name})
        details = data.get("details") or {}
        context_length = None
        for key, value in (data.get("model_info") or {}).items():
            if key.endswith(".context_length") and isinstance(value, int):
                context_length = value
                break
        capabilities = data.get("capabilities")
        info = ModelInfo(
            provider=self.name,
            name=name,
            size_bytes=size_hint,
            family=details.get("family"),
            parameter_size=details.get("parameter_size"),
            quantization=details.get("quantization_level"),
            context_length=context_length,
            capabilities=[str(c) for c in capabilities] if isinstance(capabilities, list) else [],
        )
        self._model_cache[name] = info
        return info

    async def chat_stream(
        self,
        messages: list[ChatMessage],
        *,
        model: str,
        params: GenerationParams,
        tools: list[dict[str, Any]] | None = None,
    ) -> AsyncIterator[ChatChunk]:
        info = await self.get_model(model)
        body: dict[str, Any] = {
            "model": model,
            "messages": [self._to_ollama_message(m) for m in messages],
            "stream": True,
            "options": self._options(params),
        }
        if "thinking" in info.capabilities:
            body["think"] = params.think if params.think is not None else self._default_think
        if tools:
            body["tools"] = tools

        try:
            async with self._client.stream("POST", "/api/chat", json=body) as response:
                if response.status_code != 200:
                    await response.aread()
                    message = self._error_message(response)
                    if response.status_code == 404:
                        self._model_cache.pop(model, None)
                        raise ModelNotFoundError(message)
                    raise _provider_error(message)

                async for line in response.aiter_lines():
                    if not line.strip():
                        continue
                    try:
                        data = json.loads(line)
                    except json.JSONDecodeError as exc:
                        raise ProviderError("Fragmento de respuesta no válido.") from exc
                    if isinstance(data.get("error"), str):
                        raise _provider_error(str(data["error"]))

                    message_data = data.get("message") or {}
                    thinking = message_data.get("thinking")
                    if thinking:
                        yield ThinkingDelta(str(thinking))
                    content = message_data.get("content")
                    if content:
                        yield TextDelta(str(content))
                    for call in message_data.get("tool_calls") or []:
                        function = call.get("function") or {}
                        arguments = function.get("arguments")
                        yield ToolCallRequest(
                            id=str(call.get("id") or uuid.uuid4().hex),
                            name=str(function.get("name", "")),
                            arguments=arguments if isinstance(arguments, dict) else {},
                        )
                    if data.get("done"):
                        yield Done(
                            usage=Usage(
                                prompt_tokens=int(data.get("prompt_eval_count") or 0),
                                completion_tokens=int(data.get("eval_count") or 0),
                                total_duration_ms=int(data.get("total_duration") or 0)
                                // _NS_PER_MS,
                            ),
                            done_reason=data.get("done_reason"),
                        )
                        return
        except (httpx.ConnectError, httpx.ConnectTimeout) as exc:
            raise ProviderUnavailableError(
                "No se puede conectar con Ollama. ¿Está en ejecución?"
            ) from exc
        except httpx.TimeoutException as exc:
            raise ProviderUnavailableError("Ollama dejó de responder (tiempo agotado).") from exc
        except httpx.HTTPError as exc:
            raise ProviderError(f"Conexión con Ollama interrumpida: {type(exc).__name__}") from exc
        raise ProviderError("La respuesta de Ollama terminó de forma inesperada.")

    async def embed(self, texts: list[str], *, model: str) -> list[list[float]]:
        data = await self._request_json(
            "POST", "/api/embed", json_body={"model": model, "input": texts}
        )
        embeddings = data.get("embeddings")
        if not isinstance(embeddings, list) or len(embeddings) != len(texts):
            raise ProviderError("Respuesta de embeddings no válida.")
        return [[float(x) for x in vector] for vector in embeddings]

    async def aclose(self) -> None:
        await self._client.aclose()
