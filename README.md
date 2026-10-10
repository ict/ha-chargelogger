# Chargelogger for Home Assistant

Custom integration for [EVLogger (Chargelogger)](https://github.com/ict/evlogger), a self-hosted EV charging and
expense tracker. It shows this month's charging statistics and lets you book recurring expenses
(parking, car wash, ...) with one button press.

Requires Home Assistant 2026.10 or newer. No extra Python dependencies.

## Installation

### HACS (custom repository)

1. HACS -> three-dot menu -> *Custom repositories*.
2. Add `https://github.com/ict/ha-chargelogger` as category *Integration*.
3. Install *Chargelogger* and restart Home Assistant.

### Manual

Copy `custom_components/chargelogger` into your Home Assistant `config/custom_components/` directory and restart.

## Setup

*Settings -> Devices & services -> Add integration -> Chargelogger*

- **API URL**: base URL of the API including the `/api` path, e.g. `https://chargelogger.example.com/api`.
- **API token**: a personal token (starts with `clk_`) created in Chargelogger.

The token is validated against `/users/me`. One Chargelogger account can only be added once. If the token is
revoked, Home Assistant starts a re-authentication flow. URL and token can be changed via *Reconfigure*.

**Options**: the currency used for cost sensors and preset amounts (ISO 4217 code, default `EUR`).
Chargelogger itself stores plain amounts without a currency.

## Entities

Data is polled every 15 minutes (and right after a booking). Statistics cover the current calendar month in
Home Assistant's time zone; `last_reset` is the start of that month, so the sensors work with the long-term
statistics / Energy dashboard.

| Device | Entity | Notes |
| --- | --- | --- |
| Account | Energy charged this month | kWh, `energy`, state class `total` |
| Account | Charging cost this month | currency, `monetary`, attribute `charges_without_price` |
| Account | Charges this month | count |
| Each active car | the same three sensors | retired cars (sale date set) get no entities |
| Each preset | one button | see below |

Cars added later appear automatically; cars that are retired or deleted make their sensors unavailable.

## Quick-action presets

Presets are **config subentries**: on the integration card choose *Add preset*. Each preset has a name, a car,
a category, a kind (expense or income), an amount in your currency (stored as cents) and an optional note.
Every preset becomes a button entity on its own device. Pressing it books an expense dated *now*; afterwards
the data is refreshed. A second press of the same button within 10 seconds is ignored (a warning is logged).
Failures (server unreachable, rejected request, bad token) are reported as translated errors.
Edit or delete a preset from the same card (*Edit preset* / *Delete*).

Categories: insurance, tax, tires, tolls & parking, cleaning, maintenance, accessories, subscriptions, other.

## Service action `chargelogger.add_expense`

| Field | Required | Description |
| --- | --- | --- |
| `config_entry_id` | if several accounts | account to use |
| `car_id` | yes | Chargelogger car ID |
| `category` | yes | one of the categories above |
| `amount` | yes | positive, in currency units (`12.5`) |
| `kind` | no | `expense` (default) or `income` |
| `note` | no | free text |
| `date` | no | defaults to now |

```yaml
action: chargelogger.add_expense
data:
  car_id: "your-car-id"
  category: tires
  amount: 89.9
  note: Winter tires
```

## Example dashboard card

```yaml
type: entities
title: Charging
entities:
  - entity: sensor.chargelogger_alice_energy_charged_this_month
  - entity: sensor.chargelogger_alice_charging_cost_this_month
  - entity: sensor.chargelogger_alice_charges_this_month
  - type: buttons
    entities:
      - entity: button.garage_fee
      - entity: button.car_wash
```

(Entity IDs depend on your account name and preset names.)

## Diagnostics

*Download diagnostics* redacts the API URL and token.

## Development

```bash
uv sync
uv run ruff format . && uv run ruff check .
uv run pytest
```

MIT licensed.
