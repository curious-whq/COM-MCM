"""Typed module composition for operational µMCM models."""

from umcm.composition.engine import (
    CompositionResult,
    LoadedModule,
    compose_modules,
)
from umcm.composition.parameterization import (
    TraceRoleSpec,
    render_template,
    resolve_trace_roles,
    template_placeholders,
)
from umcm.composition.model import (
    COMPOSITION_SCHEMA_VERSION,
    MODULE_SCHEMA_VERSION,
    CompositionSpec,
    ConnectionMode,
    ConnectionSpec,
    ModulePort,
    ModuleReference,
    ModuleSpec,
    PortDirection,
    PortEndpoint,
)

__all__ = [
    "COMPOSITION_SCHEMA_VERSION",
    "MODULE_SCHEMA_VERSION",
    "CompositionResult",
    "CompositionSpec",
    "ConnectionMode",
    "ConnectionSpec",
    "LoadedModule",
    "ModulePort",
    "ModuleReference",
    "ModuleSpec",
    "PortDirection",
    "PortEndpoint",
    "TraceRoleSpec",
    "render_template",
    "resolve_trace_roles",
    "template_placeholders",
    "compose_modules",
]
