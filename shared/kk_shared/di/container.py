"""Container de Injeção de Dependência mínimo e explícito.

Registra fábricas por chave (tipo/Protocol ou string) com escopo singleton ou
transient. Sem mágica: as composições (composition roots) de cada app montam o
grafo aqui e resolvem o que precisam.
"""
from __future__ import annotations

from typing import Any, Callable, TypeVar

T = TypeVar("T")


class Container:
    def __init__(self) -> None:
        self._factories: dict[Any, Callable[["Container"], Any]] = {}
        self._singletons: dict[Any, Any] = {}
        self._is_singleton: dict[Any, bool] = {}

    def register(self, key: Any, factory: Callable[["Container"], Any], *, singleton: bool = True) -> None:
        self._factories[key] = factory
        self._is_singleton[key] = singleton

    def register_instance(self, key: Any, instance: Any) -> None:
        self._singletons[key] = instance
        self._is_singleton[key] = True

    def resolve(self, key: Any) -> Any:
        if key in self._singletons:
            return self._singletons[key]
        if key not in self._factories:
            raise KeyError(f"Dependência não registrada: {key!r}")
        instance = self._factories[key](self)
        if self._is_singleton.get(key, True):
            self._singletons[key] = instance
        return instance
