"""Runtime extension contract for allowlisted specialist Agent types."""

from get_stock.agent_plugins.builtins import build_builtin_agent_types
from get_stock.agent_plugins.registry import AgentTypeRegistry
from get_stock.agent_plugins.spec import AgentTypeSpec

__all__ = ["AgentTypeRegistry", "AgentTypeSpec", "build_builtin_agent_types"]
