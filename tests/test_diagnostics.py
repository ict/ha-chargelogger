"""Diagnostics tests."""

from __future__ import annotations

import json
from typing import TYPE_CHECKING

from homeassistant.components.diagnostics import REDACTED

from custom_components.chargelogger.diagnostics import async_get_config_entry_diagnostics

from .conftest import TOKEN

if TYPE_CHECKING:
    from homeassistant.core import HomeAssistant
    from pytest_homeassistant_custom_component.common import MockConfigEntry


async def test_token_and_url_redacted(hass: HomeAssistant, setup: MockConfigEntry) -> None:
    diag = await async_get_config_entry_diagnostics(hass, setup)
    assert diag['entry'] == {'url': REDACTED, 'token': REDACTED}
    assert TOKEN not in json.dumps(diag, default=str)


async def test_diagnostics_contains_data(hass: HomeAssistant, setup: MockConfigEntry) -> None:
    diag = await async_get_config_entry_diagnostics(hass, setup)
    assert diag['data']['total']['count'] == 3
    assert len(diag['presets']) == 1
