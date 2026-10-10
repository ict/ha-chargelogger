"""Constants for the Chargelogger integration."""

from datetime import timedelta

DOMAIN = 'chargelogger'

CONF_URL = 'url'
CONF_TOKEN = 'token'  # noqa: S105
CONF_CURRENCY = 'currency'

DEFAULT_CURRENCY = 'EUR'
SCAN_INTERVAL = timedelta(minutes=15)
REQUEST_TIMEOUT = 15
PRESS_GUARD_SECONDS = 10

SUBENTRY_PRESET = 'preset'
CONF_CAR_ID = 'car_id'
CONF_CAR = 'car'
CAR_MODEL = 'Car'
CONF_CATEGORY = 'category'
CONF_KIND = 'kind'
CONF_AMOUNT = 'amount'
CONF_NOTE = 'note'
CONF_DATE = 'date'
CONF_CONFIG_ENTRY_ID = 'config_entry_id'

CATEGORIES = [
    'insurance',
    'tax',
    'tires',
    'tolls_parking',
    'cleaning',
    'maintenance',
    'accessories',
    'subscriptions',
    'other',
]
KINDS = ['expense', 'income']

CONF_CPO = 'cpo'
CONF_KWH = 'kwh'
CONF_CHARGE_TYPE = 'charge_type'
CONF_ODOMETER = 'odometer'
CONF_KM_DRIVEN = 'km_driven'
CONF_PRICE_TOTAL = 'price_total'
CONF_SOC_AFTER = 'soc_after'
CHARGE_TYPES = ['AC', 'DC']
