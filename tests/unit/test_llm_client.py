from __future__ import annotations


def test_get_client_function_exists() -> None:
    """_get_client factory function must exist."""
    import curriculum_agent.llm as llm_module

    assert hasattr(llm_module, "_get_client"), "_get_client factory function must exist"
    assert callable(llm_module._get_client)
