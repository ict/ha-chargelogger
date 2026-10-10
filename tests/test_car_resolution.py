"""How service actions find the car: device, name or Chargelogger id."""

from __future__ import annotations

from typing import TYPE_CHECKING

import pytest
from homeassistant.exceptions import ServiceValidationError
from homeassistant.helpers import device_registry as dr

from custom_components.chargelogger.const import DOMAIN

from .conftest import CAR_A, CAR_B

if TYPE_CHECKING:
    from homeassistant.core import HomeAssistant
    from pytest_homeassistant_custom_component.common import MockConfigEntry
    from pytest_homeassistant_custom_component.test_util.aiohttp import AiohttpClientMocker


def _expense_cars(api: AiohttpClientMocker) -> list[str]:
    return [call[2]['car_id'] for call in api.mock_calls if call[0] == 'POST' and str(call[1]).endswith('/expense/')]


async def _expense(hass: HomeAssistant, **data) -> None:
    await hass.services.async_call(DOMAIN, 'add_expense', {'category': 'cleaning', 'amount': 12, **data}, blocking=True)


def _car_device(hass: HomeAssistant, entry: MockConfigEntry, car_id: str) -> dr.DeviceEntry:
    registry = dr.async_get(hass)
    ident = (DOMAIN, f'{entry.entry_id}_{car_id}')
    device = registry.async_get_device_by_identifier(
        ident, entry.entry_id
    ) or registry.async_get_child_device_by_identifier(ident, entry.entry_id)
    assert device is not None
    return device


async def test_car_device_shows_id(hass: HomeAssistant, setup: MockConfigEntry) -> None:
    device = _car_device(hass, setup, CAR_A)
    assert device.serial_number == CAR_A
    assert device.model == 'Car'


async def test_by_device(hass: HomeAssistant, setup: MockConfigEntry, api: AiohttpClientMocker) -> None:
    await _expense(hass, car=_car_device(hass, setup, CAR_B).id)
    assert _expense_cars(api) == [CAR_B]


async def test_by_name_case_insensitive(hass: HomeAssistant, setup: MockConfigEntry, api: AiohttpClientMocker) -> None:
    await _expense(hass, car='alpha')
    assert _expense_cars(api) == [CAR_A]


async def test_by_chargelogger_id(hass: HomeAssistant, setup: MockConfigEntry, api: AiohttpClientMocker) -> None:
    await _expense(hass, car=CAR_B)
    assert _expense_cars(api) == [CAR_B]


async def test_add_charge_by_name(hass: HomeAssistant, setup: MockConfigEntry, api: AiohttpClientMocker) -> None:
    await hass.services.async_call(
        DOMAIN, 'add_charge', {'car': 'Beta', 'cpo': 'Home Wallbox', 'kwh': 10, 'km_driven': 50}, blocking=True
    )
    (body,) = [call[2] for call in api.mock_calls if call[0] == 'POST' and str(call[1]).endswith('/charge/')]
    assert body['car_id'] == CAR_B


async def test_account_device_is_not_a_car(
    hass: HomeAssistant, setup: MockConfigEntry, api: AiohttpClientMocker
) -> None:
    account = dr.async_get(hass).async_get_device_by_identifier((DOMAIN, setup.entry_id), setup.entry_id)
    with pytest.raises(ServiceValidationError, match='not a Chargelogger car'):
        await _expense(hass, car=account.id)
    assert not _expense_cars(api)


async def test_car_or_car_id_required(hass: HomeAssistant, setup: MockConfigEntry) -> None:
    with pytest.raises(Exception, match='car'):
        await _expense(hass)


async def test_not_both_car_and_car_id(hass: HomeAssistant, setup: MockConfigEntry) -> None:
    with pytest.raises(Exception, match='not both'):
        await _expense(hass, car='Alpha', car_id=CAR_A)


async def test_ambiguous_name(hass: HomeAssistant, setup: MockConfigEntry, api: AiohttpClientMocker) -> None:
    coordinator = setup.runtime_data
    beta = coordinator.data.cars[CAR_B]
    # Rename Beta to Alpha in the cached data to simulate two cars with the same name.
    coordinator.data.cars[CAR_B] = type(beta)(id=beta.id, name='Alpha', retired=beta.retired)
    with pytest.raises(ServiceValidationError, match='Several cars'):
        await _expense(hass, car='Alpha')
    assert not _expense_cars(api)
