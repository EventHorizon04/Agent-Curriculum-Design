from __future__ import annotations


def test_llm_module_has_no_global_client() -> None:
    """llm.py must not instantiate AsyncOpenAI at import time."""
    import curriculum_agent.llm as llm_module

    # After this import, _client must NOT exist as a module-level attribute
    assert not hasattr(llm_module, "_client"), (
        "_client must not be a module-level singleton; use _get_client() factory instead"
    )


def test_get_client_function_exists() -> None:
    """_get_client factory function must exist."""
    import curriculum_agent.llm as llm_module

    assert hasattr(llm_module, "_get_client"), "_get_client factory function must exist"
    assert callable(llm_module._get_client)
