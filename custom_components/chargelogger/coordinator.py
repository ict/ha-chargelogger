"""Data update coordinator for Chargelogger."""

from __future__ import annotations

import logging
from dataclasses import dataclass
from typing import TYPE_CHECKING, Any

from homeassistant.exceptions import ConfigEntryAuthFailed, HomeAssistantError
from homeassistant.helpers.update_coordinator import DataUpdateCoordinator, UpdateFailed
from homeassistant.util import dt as dt_util

from .api import (
    Car,
    ChargeloggerAuthError,
    ChargeloggerClient,
    ChargeloggerConnectionError,
    ChargeloggerError,
    Stats,
)
from .const import DOMAIN, SCAN_INTERVAL

if TYPE_CHECKING:
    from datetime import datetime

    from homeassistant.config_entries import ConfigEntry
    from homeassistant.core import HomeAssistant

_LOGGER = logging.getLogger(__name__)

type ChargeloggerConfigEntry = ConfigEntry[ChargeloggerCoordinator]


@dataclass(frozen=True, slots=True)
class ChargeloggerData:
    """Snapshot of one coordinator update."""

    month_start: datetime
    cars: dict[str, Car]
    total: Stats
    per_car: dict[str, Stats]

    @property
    def active_cars(self) -> dict[str, Car]:
        """Cars that are not retired."""
        return {car_id: car for car_id, car in self.cars.items() if not car.retired}


def month_start(now: datetime) -> datetime:
    """Return the start of the month of ``now`` in its own time zone."""
    return now.replace(day=1, hour=0, minute=0, second=0, microsecond=0)


class ChargeloggerCoordinator(DataUpdateCoordinator[ChargeloggerData]):
    """Fetch cars and this month's statistics."""

    config_entry: ChargeloggerConfigEntry

    def __init__(self, hass: HomeAssistant, entry: ChargeloggerConfigEntry, client: ChargeloggerClient) -> None:
        """Initialize the coordinator."""
        super().__init__(hass, _LOGGER, config_entry=entry, name=DOMAIN, update_interval=SCAN_INTERVAL)
        self.client = client
        self.account_device_id = ''

    async def _async_update_data(self) -> ChargeloggerData:
        start = month_start(dt_util.now())
        try:
            cars = await self.client.get_cars()
            stats = await self.client.get_stats(start)
        except ChargeloggerAuthError as err:
            raise ConfigEntryAuthFailed(translation_domain=DOMAIN, translation_key='invalid_auth') from err
        except ChargeloggerError as err:
            raise UpdateFailed(
                translation_domain=DOMAIN, translation_key='update_failed', translation_placeholders={'error': str(err)}
            ) from err
        return ChargeloggerData(
            month_start=start,
            cars={car.id: car for car in cars},
            total=stats.total,
            per_car=stats.per_car,
        )

    async def async_create_expense(
        self,
        *,
        car_id: str,
        category: str,
        kind: str,
        amount_cents: int,
        note: str | None = None,
        date: datetime | None = None,
    ) -> None:
        """Create an expense and refresh; raises a translated HomeAssistantError on failure."""
        body: dict[str, Any] = {
            'date': (date or dt_util.now()).isoformat(),
            'car_id': car_id,
            'category': category,
            'kind': kind,
            'amount': amount_cents,
        }
        if note:
            body['note'] = note
        try:
            await self.client.create_expense(body)
        except ChargeloggerAuthError as err:
            self.config_entry.async_start_reauth(self.hass)
            raise HomeAssistantError(translation_domain=DOMAIN, translation_key='invalid_auth') from err
        except ChargeloggerConnectionError as err:
            raise HomeAssistantError(
                translation_domain=DOMAIN,
                translation_key='cannot_connect',
                translation_placeholders={'error': str(err)},
            ) from err
        except ChargeloggerError as err:
            raise HomeAssistantError(
                translation_domain=DOMAIN,
                translation_key='expense_rejected',
                translation_placeholders={'error': str(err)},
            ) from err
        await self.async_request_refresh()
