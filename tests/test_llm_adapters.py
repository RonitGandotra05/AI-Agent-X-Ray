"""Provider transport contracts without network calls or provider packages."""

import importlib
import sys
from types import SimpleNamespace

import pytest
from xray_api.agents.llm_adapters import get_adapter
from xray_api.agents.llm_adapters.openai_compatible import provider_options
from xray_api.agents.llm_adapters.ollama import OllamaAdapter


@pytest.mark.parametrize("provider", ["openai", "cerebras", "groq", "openrouter"])
def test_compatible_adapters_share_bounded_transport_and_usage(monkeypatch, provider):
    options = {}
    calls = []
    response = SimpleNamespace(choices=[SimpleNamespace(finish_reason="stop", message=SimpleNamespace(content="{}", refusal=None))],
                               usage=SimpleNamespace(prompt_tokens=9, completion_tokens=3, total_tokens=12,
                                                     prompt_tokens_details=SimpleNamespace(cached_tokens=4)))
    class Client:
        def __init__(self, **kwargs):
            options.update(kwargs)
            self.chat = SimpleNamespace(completions=SimpleNamespace(create=self.create))
        def create(self, **kwargs):
            calls.append(kwargs)
            return response
    monkeypatch.setitem(sys.modules, "openai", SimpleNamespace(OpenAI=Client))
    monkeypatch.setenv(f"{provider.upper()}_API_KEY", "secret")
    monkeypatch.delenv(f"{provider.upper()}_MODEL", raising=False)
    monkeypatch.setenv("XRAY_LLM_TIMEOUT", "7")
    monkeypatch.setenv("XRAY_LLM_MAX_RETRIES", "1")
    adapter = get_adapter(f" {provider.upper()} ")
    assert adapter.chat_completion([{"role": "user", "content": "JSON"}]) == "{}"
    text, usage = adapter.chat_completion_with_usage([{"role": "user", "content": "JSON"}], max_tokens=55)
    assert text == "{}" and usage["cached_tokens"] == 4
    assert options["timeout"] == 7 and options["max_retries"] == 1
    assert calls[-1]["response_format"] == {"type": "json_object"}
    assert calls[-1]["max_tokens"] == 55
    assert adapter.provider_name == provider


@pytest.mark.parametrize("choices", [[],
    [SimpleNamespace(finish_reason="length", message=SimpleNamespace(content="{}"))],
    [SimpleNamespace(finish_reason="content_filter", message=SimpleNamespace(content="{}"))],
    [SimpleNamespace(finish_reason="stop", message=SimpleNamespace(content=None))],
    [SimpleNamespace(finish_reason="stop", message=SimpleNamespace(content="{}", refusal="No"))],
])
def test_compatible_adapters_reject_empty_refused_or_partial_responses(monkeypatch, choices):
    client = SimpleNamespace(chat=SimpleNamespace(completions=SimpleNamespace(create=lambda **kwargs: SimpleNamespace(choices=choices, usage=None))))
    monkeypatch.setitem(sys.modules, "openai", SimpleNamespace(OpenAI=lambda **kwargs: client))
    monkeypatch.setenv("OPENAI_API_KEY", "secret")
    with pytest.raises(ValueError):
        get_adapter("openai").chat_completion([])


@pytest.mark.parametrize("variable,value", [("XRAY_LLM_TIMEOUT", "nan"), ("XRAY_LLM_TIMEOUT", "0"),
    ("XRAY_LLM_TIMEOUT", "bad"), ("XRAY_LLM_MAX_RETRIES", "6"), ("XRAY_LLM_MAX_RETRIES", "-1")])
def test_invalid_provider_settings_raise(monkeypatch, variable, value):
    monkeypatch.setenv("XRAY_LLM_TIMEOUT", "20")
    monkeypatch.setenv("XRAY_LLM_MAX_RETRIES", "0")
    monkeypatch.setenv(variable, value)
    with pytest.raises(ValueError):
        provider_options()


def test_factory_rejects_unknown_provider():
    with pytest.raises(ValueError, match="Unknown LLM provider"):
        get_adapter("missing")


def test_anthropic_joins_text_blocks_passes_temperature_and_checks_stop(monkeypatch):
    calls = []
    response = SimpleNamespace(stop_reason="end_turn", content=[SimpleNamespace(type="thinking", thinking="hidden"),
                                                               SimpleNamespace(type="text", text="{"),
                                                               SimpleNamespace(type="text", text="}")],
                               usage=SimpleNamespace(input_tokens=4, output_tokens=2, cache_read_input_tokens=3,
                                                     cache_creation_input_tokens=1))
    def create(**kwargs):
        calls.append(kwargs)
        return response
    def constructor(**kwargs):
        assert kwargs["timeout"] == 20 and kwargs["max_retries"] == 0
        return SimpleNamespace(messages=SimpleNamespace(create=create))
    monkeypatch.setitem(sys.modules, "anthropic", SimpleNamespace(Anthropic=constructor))
    monkeypatch.setenv("ANTHROPIC_API_KEY", "secret")
    monkeypatch.setenv("XRAY_LLM_TIMEOUT", "20")
    monkeypatch.setenv("XRAY_LLM_MAX_RETRIES", "0")
    adapter = get_adapter("anthropic")
    text, usage = adapter.chat_completion_with_usage([{"role": "system", "content": "A"}, {"role": "system", "content": "B"},
                                                    {"role": "user", "content": "JSON"}], temperature=0.2)
    assert text == "{}" and usage["total_tokens"] == 10 and usage["cached_tokens"] == 3
    assert calls[0]["temperature"] == 0.2 and calls[0]["system"] == "A\nB"
    response.stop_reason = "max_tokens"
    with pytest.raises(ValueError):
        adapter.chat_completion([])


def test_ollama_checks_completion_and_uses_json_mode(monkeypatch):
    calls = []
    data = {"done": True, "done_reason": "stop", "message": {"content": "{}"}, "prompt_eval_count": 5, "eval_count": 2}
    class Response:
        def raise_for_status(self):
            pass
        def json(self):
            return data
    class Session:
        def post(self, *args, **kwargs):
            calls.append(kwargs)
            return Response()
    monkeypatch.setattr("xray_api.agents.llm_adapters.ollama.requests.Session", Session)
    monkeypatch.setenv("XRAY_LLM_TIMEOUT", "20")
    monkeypatch.setenv("XRAY_LLM_MAX_RETRIES", "0")
    adapter = OllamaAdapter()
    assert adapter.chat_completion_with_usage([]) == ("{}", {"prompt_tokens": 5, "completion_tokens": 2, "total_tokens": 7})
    assert calls[0]["json"]["format"] == "json" and calls[0]["timeout"] == 20
    data["done_reason"] = "length"
    with pytest.raises(ValueError):
        adapter.chat_completion([])


def test_api_import_does_not_import_provider_libraries(monkeypatch):
    # Blocking modules proves importing the app does not require optional SDKs.
    monkeypatch.setitem(sys.modules, "openai", None)
    monkeypatch.setitem(sys.modules, "anthropic", None)
    importlib.import_module("xray_api.app")
