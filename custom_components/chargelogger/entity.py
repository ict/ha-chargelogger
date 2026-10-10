"""Shared entity helpers."""

from __future__ import annotations

from homeassistant.helpers.device_registry import DeviceInfo
from homeassistant.helpers.update_coordinator import CoordinatorEntity

from .const import CAR_MODEL, DOMAIN
from .coordinator import ChargeloggerCoordinator


def account_device(entry_id: str, title: str) -> DeviceInfo:
    """Device info for the account-wide device."""
    return DeviceInfo(identifiers={(DOMAIN, entry_id)}, name=title, manufacturer='Chargelogger')


def car_device(entry_id: str, account_device_id: str, car_id: str, car_name: str) -> DeviceInfo:
    """Device info for a car, linked to the account device."""
    return DeviceInfo(
        identifiers={(DOMAIN, f'{entry_id}_{car_id}')},
        name=car_name,
        manufacturer='Chargelogger',
        model=CAR_MODEL,
        serial_number=car_id,  # shows the Chargelogger car ID on the device page
        via_device_id=account_device_id,
    )


def preset_device(entry_id: str, account_device_id: str, subentry_id: str, title: str) -> DeviceInfo:
    """Device info for a quick-action preset (one device per subentry)."""
    return DeviceInfo(
        identifiers={(DOMAIN, f'{entry_id}_preset_{subentry_id}')},
        name=title,
        manufacturer='Chargelogger',
        model='Quick action',
        via_device_id=account_device_id,
    )


class ChargeloggerEntity(CoordinatorEntity[ChargeloggerCoordinator]):
    """Base class for Chargelogger entities."""

    _attr_has_entity_name = True
