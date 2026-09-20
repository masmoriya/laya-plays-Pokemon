"""Provider contract. Providers choose intent; controller owns mechanics."""

from typing import Protocol


class DecisionProvider(Protocol):
    def decide_tactical(self, state: dict, options: dict) -> dict: ...

    def decide_strategy(self, state: dict, memory: list[dict]) -> dict: ...

    def recover(self, state: dict, history: list[dict]) -> dict: ...

    def generate_commentary(self, event: dict) -> str: ...

