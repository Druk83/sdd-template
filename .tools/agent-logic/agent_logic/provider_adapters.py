'''Provider-isolated test adapters for the neutral integration contract.'''
from __future__ import annotations

from .agent_adapter import FakeAgentAdapter


class _ProviderTestAdapter:
    def __init__(self, expected_model_version: str):
        self._delegate = FakeAgentAdapter(expected_model_version)

    def receive(self, message: object) -> dict:
        return self._delegate.receive(message)


class FakeCodexAdapter(_ProviderTestAdapter):
    '''Fake adapter with the Codex integration boundary.'''


class FakeCopilotAdapter(_ProviderTestAdapter):
    '''Fake adapter with the Copilot integration boundary.'''