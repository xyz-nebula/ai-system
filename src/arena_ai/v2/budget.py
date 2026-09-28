"""Task-local call budget shared by every v2 model role in a managed turn."""

from contextvars import ContextVar
from dataclasses import dataclass


@dataclass
class ModelBudget:
    remaining: int


current_budget: ContextVar[ModelBudget | None] = ContextVar("v2_model_budget", default=None)
