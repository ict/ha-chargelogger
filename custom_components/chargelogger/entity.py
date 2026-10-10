"""Shared entity helpers."""

from __future__ import annotations

from homeassistant.helpers.device_registry import DeviceInfo
from homeassistant.helpers.update_coordinator import CoordinatorEntity

from .const import DOMAIN
from .coordinator import ChargeloggerCoordinator


def account_device(entry_id: str, title: str) -> DeviceInfo:
    """Device info for the account-wide device."""
    return DeviceInfo(identifiers={(DOMAIN, entry_id)}, name=title, manufacturer='Chargelogger')


def car_device(entry_id: str, car_id: str, car_name: str) -> DeviceInfo:
    """Device info for a car, linked to the account device."""
    return DeviceInfo(
        identifiers={(DOMAIN, f'{entry_id}_{car_id}')},
        name=car_name,
        manufacturer='Chargelogger',
        via_device=(DOMAIN, entry_id),
    )


class ChargeloggerEntity(CoordinatorEntity[ChargeloggerCoordinator]):
    """Base class for Chargelogger entities."""

    _attr_has_entity_name = True
