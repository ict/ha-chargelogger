"""The Chargelogger integration."""

from __future__ import annotations

from typing import TYPE_CHECKING

from homeassistant.const import Platform
from homeassistant.helpers import device_registry as dr
from homeassistant.helpers.aiohttp_client import async_get_clientsession

from .api import ChargeloggerClient
from .const import CONF_TOKEN, CONF_URL, DOMAIN
from .coordinator import ChargeloggerConfigEntry, ChargeloggerCoordinator
from .services import async_setup_services

if TYPE_CHECKING:
    from homeassistant.core import HomeAssistant
    from homeassistant.helpers.typing import ConfigType

PLATFORMS = [Platform.BUTTON, Platform.SENSOR]

__all__ = ['DOMAIN', 'async_setup', 'async_setup_entry', 'async_unload_entry']


async def async_setup(hass: HomeAssistant, config: ConfigType) -> bool:
    """Register service actions (done here so they exist without a loaded entry)."""
    async_setup_services(hass)
    return True


async def async_setup_entry(hass: HomeAssistant, entry: ChargeloggerConfigEntry) -> bool:
    """Set up Chargelogger from a config entry."""
    client = ChargeloggerClient(async_get_clientsession(hass), entry.data[CONF_URL], entry.data[CONF_TOKEN])
    coordinator = ChargeloggerCoordinator(hass, entry, client)
    # Raises ConfigEntryNotReady / ConfigEntryAuthFailed as appropriate.
    await coordinator.async_config_entry_first_refresh()
    entry.runtime_data = coordinator
    account = dr.async_get(hass).async_get_or_create(
        config_entry_id=entry.entry_id,
        identifiers={(DOMAIN, entry.entry_id)},
        name=entry.title,
        manufacturer='Chargelogger',
    )
    coordinator.account_device_id = account.id

    await hass.config_entries.async_forward_entry_setups(entry, PLATFORMS)
    entry.async_on_unload(entry.add_update_listener(_async_update_listener))
    return True


async def async_unload_entry(hass: HomeAssistant, entry: ChargeloggerConfigEntry) -> bool:
    """Unload a config entry."""
    return await hass.config_entries.async_unload_platforms(entry, PLATFORMS)


async def _async_update_listener(hass: HomeAssistant, entry: ChargeloggerConfigEntry) -> None:
    """Reload when options or presets (subentries) change."""
    await hass.config_entries.async_reload(entry.entry_id)
