"""Pruebas del proveedor Ollama (con transporte HTTP simulado) y del constructor de contexto."""

from __future__ import annotations

import json
from typing import Any

import httpx
import pytest

from app.llm.base import (
    ChatMessage,
    ContextOverflowError,
    Done,
    GenerationParams,
    ModelNotFoundError,
    ProviderError,
    ProviderUnavailableError,
    TextDelta,
    ThinkingDelta,
    ToolCallRequest,
)
from app.llm.ollama_provider import OllamaProvider
from app.modules.chat.context_builder import build_context, output_reserve

SHOW_QWEN = {
    "details": {"family": "qwen3", "parameter_size": "1.7B", "quantization_level": "Q4_K_M"},
    "model_info": {"qwen3.context_length": 40960, "general.architecture": "qwen3"},
    "capabilities": ["completion", "tools", "thinking"],
}


def ndjson(*objs: dict[str, Any]) -> bytes:
    return b"".join(json.dumps(o).encode() + b"\n" for o in objs)


def make_provider(handler: Any) -> OllamaProvider:
    return OllamaProvider("http://ollama.test", transport=httpx.MockTransport(handler))


async def collect(provider: OllamaProvider, **kwargs: Any) -> list[Any]:
    return [
        chunk
        async for chunk in provider.chat_stream(
            [ChatMessage(role="user", content="hola")],
            model=kwargs.pop("model", "qwen3:1.7b"),
            params=kwargs.pop("params", GenerationParams(temperature=0.2, num_ctx=2048)),
        )
    ]


@pytest.mark.anyio
async def test_chat_stream_parses_ndjson_and_sends_options() -> None:
    seen: dict[str, Any] = {}

    def handler(request: httpx.Request) -> httpx.Response:
        if request.url.path == "/api/show":
            return httpx.Response(200, json=SHOW_QWEN)
        seen.update(json.loads(request.content))
        return httpx.Response(
            200,
            content=ndjson(
                {
                    "message": {"role": "assistant", "content": "", "thinking": "pienso"},
                    "done": False,
                },
                {"message": {"role": "assistant", "content": "Ho"}, "done": False},
                {"message": {"role": "assistant", "content": "la"}, "done": False},
                {
                    "message": {
                        "role": "assistant",
                        "content": "",
                        "tool_calls": [{"function": {"name": "f", "arguments": {"a": 1}}}],
                    },
                    "done": False,
                },
                {
                    "message": {"role": "assistant", "content": ""},
                    "done": True,
                    "done_reason": "stop",
                    "prompt_eval_count": 12,
                    "eval_count": 2,
                    "total_duration": 5_000_000,
                },
            ),
        )

    provider = make_provider(handler)
    chunks = await collect(provider)
    await provider.aclose()

    assert seen["stream"] is True
    assert seen["options"] == {"temperature": 0.2, "num_ctx": 2048}
    assert seen["think"] is False, "el modelo soporta thinking: se envía el valor por defecto"
    assert isinstance(chunks[0], ThinkingDelta)
    assert [c.text for c in chunks if isinstance(c, TextDelta)] == ["Ho", "la"]
    tool = next(c for c in chunks if isinstance(c, ToolCallRequest))
    assert tool.name == "f"
    assert tool.arguments == {"a": 1}
    done = chunks[-1]
    assert isinstance(done, Done)
    assert done.usage.prompt_tokens == 12
    assert done.usage.completion_tokens == 2
    assert done.usage.total_duration_ms == 5
    assert done.done_reason == "stop"


@pytest.mark.anyio
async def test_think_not_sent_when_model_lacks_capability() -> None:
    seen: dict[str, Any] = {}

    def handler(request: httpx.Request) -> httpx.Response:
        if request.url.path == "/api/show":
            return httpx.Response(200, json={"capabilities": ["completion"]})
        seen.update(json.loads(request.content))
        return httpx.Response(200, content=ndjson({"message": {"content": "ok"}, "done": True}))

    provider = make_provider(handler)
    await collect(provider, model="llama3.2:3b")
    assert "think" not in seen


@pytest.mark.anyio
async def test_model_not_found() -> None:
    def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(404, json={"error": "model 'x' not found"})

    with pytest.raises(ModelNotFoundError, match="not found"):
        await collect(make_provider(handler), model="x")


@pytest.mark.anyio
async def test_connection_refused_is_unavailable() -> None:
    def handler(request: httpx.Request) -> httpx.Response:
        raise httpx.ConnectError("refused", request=request)

    provider = make_provider(handler)
    with pytest.raises(ProviderUnavailableError):
        await collect(provider)
    health = await provider.health()
    assert health.ok is False


@pytest.mark.anyio
async def test_stream_error_and_truncated_stream() -> None:
    def error_handler(request: httpx.Request) -> httpx.Response:
        if request.url.path == "/api/show":
            return httpx.Response(200, json=SHOW_QWEN)
        return httpx.Response(200, content=ndjson({"error": "out of memory"}))

    with pytest.raises(ProviderError, match="out of memory"):
        await collect(make_provider(error_handler))

    def truncated(request: httpx.Request) -> httpx.Response:
        if request.url.path == "/api/show":
            return httpx.Response(200, json=SHOW_QWEN)
        return httpx.Response(200, content=ndjson({"message": {"content": "a"}, "done": False}))

    with pytest.raises(ProviderError, match="inesperada"):
        await collect(make_provider(truncated))


@pytest.mark.anyio
async def test_list_models_and_context_length() -> None:
    def handler(request: httpx.Request) -> httpx.Response:
        if request.url.path == "/api/tags":
            return httpx.Response(
                200, json={"models": [{"name": "qwen3:1.7b", "model": "qwen3:1.7b", "size": 1400}]}
            )
        return httpx.Response(200, json=SHOW_QWEN)

    models = await make_provider(handler).list_models()
    assert len(models) == 1
    assert models[0].name == "qwen3:1.7b"
    assert models[0].context_length == 40960
    assert "tools" in models[0].capabilities
    assert models[0].size_bytes == 1400


@pytest.mark.anyio
async def test_embed() -> None:
    def handler(request: httpx.Request) -> httpx.Response:
        body = json.loads(request.content)
        return httpx.Response(200, json={"embeddings": [[0.1, 0.2]] * len(body["input"])})

    vectors = await make_provider(handler).embed(["a", "b"], model="nomic-embed-text")
    assert vectors == [[0.1, 0.2], [0.1, 0.2]]


# --------------------------------------------------------------------------- contexto
def _msgs(*pairs: tuple[str, str]) -> list[ChatMessage]:
    return [ChatMessage(role=r, content=c) for r, c in pairs]  # type: ignore[arg-type]


def test_context_keeps_recent_messages_within_budget() -> None:
    history = _msgs(*[("user" if i % 2 == 0 else "assistant", "x" * 300) for i in range(40)])
    built = build_context("sistema", history, num_ctx=2048, reserve_output=512)
    assert built.messages[0].role == "system"
    assert built.messages[-1] == history[-1]
    assert built.dropped > 0
    assert built.estimated_tokens <= 2048 - 512
    assert built.messages[1].role == "user", "no debe empezar con una respuesta huérfana"


def test_context_overflow_on_huge_message() -> None:
    with pytest.raises(ContextOverflowError):
        build_context("s", _msgs(("user", "x" * 50_000)), num_ctx=2048, reserve_output=512)


def test_output_reserve() -> None:
    assert output_reserve(4096, None) == 1024
    assert output_reserve(2048, None) == 512
    assert output_reserve(4096, 300) == 300
    assert output_reserve(4096, 10_000) == 2048


def test_generation_params_merge() -> None:
    base = GenerationParams(temperature=0.7, num_ctx=4096, think=False)
    merged = GenerationParams(temperature=0.1).merged_over(base)
    assert merged.temperature == 0.1
    assert merged.num_ctx == 4096
    with pytest.raises(ValueError, match="extra"):
        GenerationParams(foo=1)  # type: ignore[call-arg]
