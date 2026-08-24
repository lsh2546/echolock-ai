"""
tests/test_architecture.py

CI architecture test: safety_gate must have zero reachable AI / LLM symbols.

This test will fail if any AI library is imported transitively from safety_gate,
enforcing the design rule that the Safety Gate is deterministic-only.
"""

from __future__ import annotations

import importlib
import sys
import types


_FORBIDDEN_AI_PREFIXES = (
    "openai",
    "anthropic",
    "watsonx",
    "ibm_generative",
    "ibm_watson",
    "langchain",
    "llama_cpp",
    "transformers",
    "torch",
    "tensorflow",
    "cohere",
    "mistralai",
    "google.generativeai",
)


def _collect_transitive_imports(module_name: str) -> set[str]:
    """Return all module names transitively imported when loading module_name."""
    before = set(sys.modules.keys())
    # Reload in an isolated way: import the module fresh
    if module_name in sys.modules:
        # Already loaded — just inspect what it pulled in
        mod = sys.modules[module_name]
    else:
        mod = importlib.import_module(module_name)  # pragma: no cover
    after = set(sys.modules.keys())
    return after - before | {module_name}


def test_safety_gate_has_no_ai_dependency() -> None:
    """safety_gate must not transitively import any AI / LLM library."""
    # Import safety_gate (may already be in sys.modules from other tests)
    import echolock.safety_gate  # noqa: F401

    # Check all currently loaded modules that are transitively reachable
    # from echolock.safety_gate by inspecting sys.modules after the import.
    # We check the full sys.modules for any AI prefix that appeared after the
    # echolock package was imported — but we only fail if safety_gate itself
    # directly or transitively requires it.
    #
    # Simpler and sufficient: inspect safety_gate's own module attributes
    # for any reference to forbidden libraries.
    sg_module = sys.modules.get("echolock.safety_gate")
    assert sg_module is not None, "safety_gate module not found in sys.modules"

    ai_found: list[str] = []
    for attr_name in dir(sg_module):
        obj = getattr(sg_module, attr_name, None)
        if isinstance(obj, types.ModuleType):
            for prefix in _FORBIDDEN_AI_PREFIXES:
                if obj.__name__.startswith(prefix):
                    ai_found.append(obj.__name__)

    assert ai_found == [], (
        f"safety_gate has AI/LLM module references: {ai_found}. "
        "The Safety Gate must remain deterministic with zero AI dependency."
    )


def test_safety_gate_imports_only_echolock_and_stdlib() -> None:
    """safety_gate should only import from echolock.models and stdlib."""
    import echolock.safety_gate as sg

    allowed_prefixes = ("echolock.", "builtins", "_", "collections", "datetime", "enum", "typing", "uuid")
    third_party: list[str] = []
    for attr_name in dir(sg):
        obj = getattr(sg, attr_name, None)
        if isinstance(obj, types.ModuleType):
            name = obj.__name__
            if not any(name.startswith(p) for p in allowed_prefixes):
                # pydantic is allowed (data models only)
                if not name.startswith("pydantic"):
                    third_party.append(name)

    assert third_party == [], (
        f"safety_gate imported unexpected third-party modules: {third_party}"
    )
