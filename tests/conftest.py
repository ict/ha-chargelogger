"""Shared fixtures."""

from __future__ import annotations

from typing import TYPE_CHECKING, Any

import pytest
from homeassistant.config_entries import ConfigSubentryData
from pytest_homeassistant_custom_component.common import MockConfigEntry

from custom_components.chargelogger.const import (
    CONF_AMOUNT,
    CONF_CAR_ID,
    CONF_CATEGORY,
    CONF_CURRENCY,
    CONF_KIND,
    CONF_NOTE,
    CONF_TOKEN,
    CONF_URL,
    DOMAIN,
    SUBENTRY_PRESET,
)

if TYPE_CHECKING:
    from homeassistant.core import HomeAssistant
    from pytest_homeassistant_custom_component.test_util.aiohttp import AiohttpClientMocker

BASE = 'https://chargelogger.example.com/api'
TOKEN = 'clk_test_secret_token'
CAR_A = 'car-a'
CAR_B = 'car-b'
CAR_OLD = 'car-old'

CARS = [
    {'id': CAR_A, 'name': 'Alpha', 'sale_date': None},
    {'id': CAR_B, 'name': 'Beta', 'sale_date': None},
    {'id': CAR_OLD, 'name': 'Old', 'sale_date': '2024-01-01'},
]
STATS = {
    'from_date': '2026-10-01T00:00:00+02:00',
    'to_date': None,
    'total': {'count': 3, 'kwh_charged': 4567, 'price_total': 1234, 'charges_without_price': 1},
    'per_car': [
        {
            'car_id': CAR_A,
            'car_name': 'Alpha',
            'count': 2,
            'kwh_charged': 4000,
            'price_total': 1000,
            'charges_without_price': 0,
        },
        {
            'car_id': CAR_OLD,
            'car_name': 'Old',
            'count': 1,
            'kwh_charged': 567,
            'price_total': 234,
            'charges_without_price': 1,
        },
    ],
}


@pytest.fixture(autouse=True)
def _enable_custom_integrations(enable_custom_integrations: None) -> None:
    """Allow loading the custom component."""


@pytest.fixture
def api(aioclient_mock: AiohttpClientMocker) -> AiohttpClientMocker:
    """Mock a healthy Chargelogger API."""
    aioclient_mock.get(f'{BASE}/users/me', json={'username': 'tester'})
    aioclient_mock.get(f'{BASE}/car/', json=CARS)
    aioclient_mock.get(f'{BASE}/charge/stats', json=STATS)
    aioclient_mock.post(f'{BASE}/expense/', status=201, json={'id': 'x'})
    return aioclient_mock


def preset(**overrides: Any) -> ConfigSubentryData:
    """Build a preset subentry."""
    data = {
        CONF_CAR_ID: CAR_A,
        CONF_CATEGORY: 'tolls_parking',
        CONF_KIND: 'expense',
        CONF_AMOUNT: 250,
        CONF_NOTE: 'Garage',
    } | overrides
    return ConfigSubentryData(data=data, subentry_type=SUBENTRY_PRESET, title='Garage fee', unique_id=None)


@pytest.fixture
def entry() -> MockConfigEntry:
    """Config entry with one preset."""
    return MockConfigEntry(
        domain=DOMAIN,
        title='Chargelogger (tester)',
        unique_id='tester',
        data={CONF_URL: BASE, CONF_TOKEN: TOKEN},
        options={CONF_CURRENCY: 'EUR'},
        subentries_data=[preset()],
    )


@pytest.fixture
async def setup(hass: HomeAssistant, api: AiohttpClientMocker, entry: MockConfigEntry) -> MockConfigEntry:
    """Set up the integration."""
    entry.add_to_hass(hass)
    assert await hass.config_entries.async_setup(entry.entry_id)
    await hass.async_block_till_done()
    return entry
