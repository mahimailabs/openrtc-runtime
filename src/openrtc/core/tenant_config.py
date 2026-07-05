"""Per-tenant provider config resolution (MAH-102).

Each tenant can run on different STT/LLM/TTS providers (with different API keys and
models) so an agency can attribute API cost to the right client. OpenRTC keeps its
provider passthrough contract: a tenant's ``stt`` / ``llm`` / ``tts`` are
``ProviderValue``s (a shorthand string, or a pre-instantiated plugin object that
carries the tenant's key), forwarded to ``AgentSession`` unchanged. OpenRTC does not
parse a ``{provider, model, api_key}`` spec (that would couple it to every plugin
SDK and break passthrough); the caller builds the plugin object, or supplies a
callable that does.

Per-tenant **prompt** overrides are out of scope here: an agent owns its own
instructions, so route a tenant to its own agent via the custom router (MAH-99) to
give it a distinct prompt. This module governs the provider clients only.
"""

from __future__ import annotations

import logging
from collections.abc import Callable, Mapping
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from openrtc.core.config import AgentConfig
    from openrtc.utils.types import ProviderValue

logger = logging.getLogger("openrtc")

__all__ = [
    "TenantConfig",
    "TenantConfigResolver",
    "TenantConfigSource",
    "resolve_tenant_providers",
]

# One tenant's provider overrides: any of "stt" / "llm" / "tts" as a ProviderValue.
# Omitted keys fall back to the agent's (or pool default) provider.
TenantConfig = Mapping[str, "ProviderValue"]
# Either a static ``{tenant: config}`` map, or a callable ``tenant -> config`` (e.g.
# a per-request DB load). A callable returning ``None`` means "no config for this
# tenant" (fall back to defaults).
TenantConfigSource = Mapping[str, TenantConfig] | Callable[[str], TenantConfig | None]


class TenantConfigResolver:
    """Resolve (and cache) a tenant's provider config; warn once on a miss."""

    def __init__(self, source: TenantConfigSource) -> None:
        self._source = source
        self._cache: dict[str, TenantConfig | None] = {}

    def resolve(self, tenant: str) -> TenantConfig | None:
        """Return the tenant's config (cached per tenant), or ``None`` on a miss.

        A callable source is invoked once per tenant and its result cached, so a
        tenant's later sessions reuse the same provider objects: one tenant's client
        (and key) never leaks into another tenant's session. A missing tenant falls
        back to the agent / pool defaults, logged once per tenant.
        """
        if tenant in self._cache:
            return self._cache[tenant]
        config = self._lookup(tenant)
        if config is None:
            logger.warning(
                "No tenant config for '%s'; falling back to the agent/pool "
                "provider defaults.",
                tenant,
            )
        self._cache[tenant] = config
        return config

    def _lookup(self, tenant: str) -> TenantConfig | None:
        source = self._source
        if callable(source):
            return source(tenant)
        return source.get(tenant)


def resolve_tenant_providers(
    config: AgentConfig, tenant_config: TenantConfig | None
) -> tuple[ProviderValue | None, ProviderValue | None, ProviderValue | None]:
    """Return ``(stt, llm, tts)`` with the tenant's overrides applied over the agent's.

    A key the tenant config omits falls back to the agent's provider, so a tenant
    can override just the ``llm`` and keep the agent's ``stt`` / ``tts``.
    """
    if tenant_config is None:
        return config.stt, config.llm, config.tts
    return (
        tenant_config.get("stt", config.stt),
        tenant_config.get("llm", config.llm),
        tenant_config.get("tts", config.tts),
    )
