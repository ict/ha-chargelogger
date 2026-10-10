"""Service action tests."""

from __future__ import annotations

from typing import TYPE_CHECKING

import pytest
from homeassistant.exceptions import HomeAssistantError, ServiceValidationError
from pytest_homeassistant_custom_component.common import MockConfigEntry

from custom_components.chargelogger.const import CONF_TOKEN, CONF_URL, DOMAIN

from .conftest import BASE, CAR_A, CAR_OLD, TOKEN

if TYPE_CHECKING:
    from homeassistant.core import HomeAssistant
    from pytest_homeassistant_custom_component.test_util.aiohttp import AiohttpClientMocker


def _posts(api: AiohttpClientMocker) -> list[dict]:
    return [call[2] for call in api.mock_calls if call[0] == 'POST']


async def _call(hass: HomeAssistant, **data) -> None:
    await hass.services.async_call(DOMAIN, 'add_expense', data, blocking=True)


async def test_service_registered_without_entry(hass: HomeAssistant) -> None:
    from homeassistant.setup import async_setup_component

    assert await async_setup_component(hass, DOMAIN, {})
    assert hass.services.has_service(DOMAIN, 'add_expense')


async def test_add_expense_defaults(hass: HomeAssistant, setup: MockConfigEntry, api: AiohttpClientMocker) -> None:
    await _call(hass, car_id=CAR_A, category='tires', amount=99.95)
    (body,) = _posts(api)
    assert body['amount'] == 9995
    assert body['kind'] == 'expense'
    assert body['category'] == 'tires'
    assert 'note' not in body


async def test_add_expense_income_with_date_and_note(
    hass: HomeAssistant, setup: MockConfigEntry, api: AiohttpClientMocker
) -> None:
    await _call(
        hass,
        config_entry_id=setup.entry_id,
        car_id=CAR_A,
        category='other',
        amount=5,
        kind='income',
        note='refund',
        date='2026-09-30 12:00:00',
    )
    (body,) = _posts(api)
    assert body['kind'] == 'income'
    assert body['note'] == 'refund'
    assert body['date'].startswith('2026-09-30T12:00:00')
    assert body['date'][-6] in '+-'


async def test_unknown_car(hass: HomeAssistant, setup: MockConfigEntry, api: AiohttpClientMocker) -> None:
    with pytest.raises(ServiceValidationError, match='does not exist'):
        await _call(hass, car_id='nope', category='tires', amount=1)
    assert not _posts(api)


async def test_retired_car_still_bookable(
    hass: HomeAssistant, setup: MockConfigEntry, api: AiohttpClientMocker
) -> None:
    await _call(hass, car_id=CAR_OLD, category='other', amount=1)
    assert len(_posts(api)) == 1


async def test_invalid_amount_rejected(hass: HomeAssistant, setup: MockConfigEntry) -> None:
    with pytest.raises(Exception, match='amount'):
        await _call(hass, car_id=CAR_A, category='tires', amount=0)


async def test_entry_id_required_with_two_entries(
    hass: HomeAssistant, setup: MockConfigEntry, api: AiohttpClientMocker
) -> None:
    second = MockConfigEntry(domain=DOMAIN, unique_id='other', data={CONF_URL: BASE, CONF_TOKEN: TOKEN})
    second.add_to_hass(hass)
    with pytest.raises(ServiceValidationError, match='config_entry_id'):
        await _call(hass, car_id=CAR_A, category='tires', amount=1)
    with pytest.raises(ServiceValidationError, match='not loaded'):
        await _call(hass, config_entry_id=second.entry_id, car_id=CAR_A, category='tires', amount=1)
    with pytest.raises(ServiceValidationError, match='not found'):
        await _call(hass, config_entry_id='missing', car_id=CAR_A, category='tires', amount=1)


async def test_api_failure_is_translated(hass: HomeAssistant, setup: MockConfigEntry, api: AiohttpClientMocker) -> None:
    api.clear_requests()
    api.post(f'{BASE}/expense/', status=422)
    with pytest.raises(HomeAssistantError, match='rejected'):
        await _call(hass, car_id=CAR_A, category='tires', amount=1)
