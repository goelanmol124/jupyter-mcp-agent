"""The pre-rename ``llm_jupyter`` import path stays a thin alias."""

from __future__ import annotations


def test_legacy_package_aliases_submodules() -> None:
    import jupyter_mcp_agent
    import jupyter_mcp_agent.session as new_session
    import llm_jupyter
    import llm_jupyter.session as old_session

    assert old_session is new_session
    assert llm_jupyter.__version__ == jupyter_mcp_agent.__version__
