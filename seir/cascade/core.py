"""Shared simulation state and the module interface every layer implements."""
from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any, Protocol


@dataclass
class SimState:
    day: int = 0
    # One slot per layer. Each is a frozen snapshot from cascade.contracts
    # (or EpiSnapshot), written by exactly one module and read by the others.
    epi: Any = None                       # EpiSnapshot, written by "seir"
    load: Any = None                      # HospitalLoad, written by "allocation"
    fdna: Any = None                      # Operability, written by "fdna"
    diversion: Any = None                 # DiversionStatus, written by "rerouting"
    access: Any = None                    # AccessSnapshot, written by "equity"
    hospitals: Any = None                 # kept for the SEIR-only tests
    # Feedback channel: signals[target_module][name] = value. A module writes
    # signals for a module earlier in the day; the target reads them next day.
    signals: dict[str, dict[str, Any]] = field(default_factory=dict)
    history: list[Any] = field(default_factory=list)


class Module(Protocol):
    name: str

    def step(self, state: SimState, t: int) -> SimState: ...


class Simulation:
    def __init__(self, modules: list[Module]):
        names = [m.name for m in modules]
        if len(set(names)) != len(names):
            raise ValueError(f"module names must be unique, got {names}")
        self.modules = modules

    def module(self, name: str) -> Module:
        return next(m for m in self.modules if m.name == name)

    def run(self, days: int, state: SimState | None = None) -> SimState:
        state = state or SimState()
        for t in range(days):
            state.day = t
            for m in self.modules:
                state = m.step(state, t)
        return state
