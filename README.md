# ☀️ Rockcore Solar (RC-C) for Home Assistant

Monitor your **Rockcore** solar microinverters in Home Assistant. 🔋

This integration works with the inverters monitored through the **RC-C** app (Shanghai Rockcore
Electronic Technology, `studio.yanxinalircc.com` /
[App Store](https://apps.apple.com/us/app/rc-c/id6572295769)). It signs in to the same cloud the app
uses and exposes your plant and every microinverter as Home Assistant devices, ready for the
**Energy dashboard** ⚡.

> ℹ️ **Not affiliated with or endorsed by Rockcore.** The cloud API is undocumented and may change
> without notice.

## 📑 Contents

- [✨ Features](#-features)
- [📦 Installation](#-installation)
- [🔧 Setup](#-setup)
- [⚡ Energy dashboard](#-energy-dashboard)
- [🚨 Alarms explained](#-alarms-explained)
- [🩺 Troubleshooting](#-troubleshooting)
- [🧠 How it works](#-how-it-works)
- [📝 Changelog](#-changelog)
- [📄 License](#-license)

---

## ✨ Features

- ☀️ **One device per plant**, plus 🔋 **one device per microinverter** linked to it.
- ⚡ Energy counters ready for the **Energy dashboard** (day, month, year and lifetime).
- 🔆 **Per-panel monitoring**: power, voltage and current of every MPPT input.
- 🚨 **Smart alarm tracking** that separates real inverter faults from grid and weather noise.
- 🆕 **Automatic discovery**: plants, inverters and MPPT inputs that appear later get their entities
  without a reload.
- 🛡️ **Safe with your account**: a rejected password is never retried automatically (the cloud
  locks the account after ten failures).

### ☀️ Entities per plant

| Entity | Unit | Notes |
| --- | --- | --- |
| Power | W | Current AC output of the whole plant |
| Energy today / this month / this year | kWh | `total_increasing` |
| **Total energy** | kWh | Lifetime yield. **Use this one in the Energy dashboard** |
| Installed capacity | kW | Diagnostic |
| Efficiency | % | Output relative to installed capacity. Diagnostic |
| CO2 avoided | kg | Diagnostic |
| Last update | timestamp | Diagnostic |
| Online | connectivity | Diagnostic |
| Active alarms | count | Open (not yet recovered) alarms across the plant's inverters |
| Latest alarm | text | Most recent alarm. Level, device and timestamps are in the attributes |
| Inverters with isolated alarms | count | Diagnostic. Per-inverter breakdown in the attributes, see [Isolated alarms](#-isolated-alarms) |
| Alarm | problem | On while any alarm is open. See [the caveat](#-open-alarms) |

### 🔋 Entities per microinverter

| Entity | Unit | Notes |
| --- | --- | --- |
| Power | W | |
| Energy today / this month / this year / total | kWh | `total_increasing` |
| Grid voltage | V | |
| Grid frequency | Hz | |
| Temperature | °C | |
| Wi-Fi signal | % | Diagnostic |
| Last update | timestamp | Diagnostic |
| PV *n* power | W | One set per MPPT input (an RC8021 has four) |
| PV *n* voltage / current | V / A | Diagnostic |
| Online | connectivity | Diagnostic |
| Alarm | problem | On while this inverter has an open alarm |

Model, firmware (OTA) version and serial number are filled in on each device.

---

## 📦 Installation

📋 **Requires Home Assistant 2025.1.0 or newer.**

### Option A: HACS (recommended)

1. Open HACS → ⋮ → **Custom repositories**.
2. Add `https://github.com/dreamelite96/ha-rockcore` with type **Integration**.
3. Install **Rockcore Solar (RC-C)**.
4. Restart Home Assistant.

### Option B: Manual

1. Copy the `custom_components/rockcore` folder into your Home Assistant
   `config/custom_components/` folder.
2. Restart Home Assistant.

---

## 🔧 Setup

1. Go to **Settings → Devices & services → Add integration**.
2. Search for **Rockcore Solar (RC-C)**.
3. Enter the **same e-mail and password you use in the RC-C app**.

> ⚠️ **Careful with the password.** The Rockcore cloud **locks the account after ten consecutive
> wrong passwords**. The integration never retries a rejected password on its own. It asks you to
> re-authenticate instead. Still, double-check the credentials in the app before retrying by hand.

### ⏱️ Polling interval

The default is **60 seconds** (range 30 to 900). Change it with the integration's **Configure**
button.

Each poll costs `2 + 2 × plants + 2 × inverters` cloud requests, for example 18 for one plant with
seven microinverters. The alarm calls are per account, so they do not grow with the plant. The 7-day
alarm history (up to 10 extra requests) is refreshed separately, every 15 minutes.

---

## ⚡ Energy dashboard

1. Go to **Settings → Dashboards → Energy → Solar panels → Add solar production**.
2. Pick the plant's **Total energy** sensor. It is the lifetime counter, **not** the daily one.

   Its entity id follows your Home Assistant language, for example `sensor.<plant>_total_energy` or
   `sensor.<plant>_energia_total`.

Good to know:

- 📈 Statistics start accumulating from the moment the sensor is added. History from before the
  integration existed is not backfilled.
- 🕐 The hourly figures only appear after the next top-of-the-hour rollup, so the first hour can look
  empty.
- ➕ If you already have another solar system in the dashboard, add this one as a **second** solar
  source. Home Assistant sums them.

---

## 🚨 Alarms explained

Alarms on this platform are noisy, so the integration offers two different views of them.

### 🔔 Open alarms

The `Alarm` binary sensors and the `Active alarms` counter report the alarms that the cloud has not
marked as recovered.

The plant's own `isAlarm` flag is **not** used: the cloud leaves it `false` even with alarms open
(measured: `isAlarm: false` while 15 alarms were unrecovered), so an entity driven by it would never
fire.

Two things to know before you automate on them:

- 📌 **The cloud never clears some alarms.** On the reference plant the four `Channel N undervoltage`
  alarms have been open since commissioning day and have no recovery event, so the `Alarm` entity
  sits at `on` permanently. **Trigger on the `Active alarms` count changing, or on the
  `active_alarm_levels` attribute, not on the state flipping.**
- 🟢 **Level 1 is routine.** `Hardware Protection` accounts for 175 of 208 alarms on the reference
  plant and self-recovers in about 183 s (median), typically across several inverters at once. That
  is a grid disturbance, not a failing unit. Levels 2 and 3 are the ones that stick.

**Attributes** of both alarm entities: `active_alarm_count`, `active_alarm_levels` and the
`active_alarms` list. The list is capped at 25 entries (`active_alarms_truncated` tells you when
that happened) to stay under Home Assistant's attribute size limit. The counts always cover every
open alarm.

### 🎯 Isolated alarms

Counting alarms tells you about the weather, not about your inverters. Over seven days on the
reference plant (335 alarms, seven inverters) the daily alarm count correlated **-0.45** with the
daily yield: the cloudiest day produced 86 alarms and the sunniest 41. 85% of the alarms hit more
than one inverter within two minutes and 31% hit all seven at once, which is a grid event, not a unit
fault.

The `Inverters with isolated alarms` sensor applies two filters instead:

1. **Isolated.** An alarm only counts if no other inverter reported the same message within two
   minutes. This removes the weather: after filtering, the count correlates **+0.31** with the yield,
   and on the cloudiest day only 9 of the 86 alarms survived.
2. **Recurrent.** An inverter is flagged only if it has isolated alarms on at least two of the last
   three days *and* its seven-day total is above the median of the fleet. The median is the control:
   on a bad day every unit collects a few isolated alarms, so the bar rises with them and nobody
   stands out.

What is left is a per-unit signal. On the reference plant two inverters have never produced a single
isolated alarm while one produced 20 across five days, and the same seven days of data flag two units
and stay quiet about the other five.

**Attributes:** `alarms_examined`, `isolated_alarms`, `fleet_median`, `flagged_inverters`, and a
`per_inverter` breakdown with `isolated`, `days`, `days_recent` and `flagged` for each unit.

> ⚠️ **This is a ranking, not a diagnosis, and it is deliberately not wired to any alert.** The
> thresholds were calibrated on a week of data that contains no actual failure, so watch the numbers
> for a while before you automate on them. It also does not replace comparing the MPPT inputs
> against each other: on the reference plant three dead panel connections produced no alarm at all.

---

## 🩺 Troubleshooting

| Symptom | What it means | What to do |
| --- | --- | --- |
| Home Assistant asks you to **re-authenticate** | The cloud rejected the password. It is never retried automatically, to protect the account | Enter the password again. If you are unsure, check it in the RC-C app first |
| `Alarm` entity is **always on** | Some alarms are never cleared by the cloud | Trigger on the `Active alarms` count or on `active_alarm_levels` instead, see [Open alarms](#-open-alarms) |
| An inverter has **no PV sensors** | It was offline when Home Assistant started and reported no inputs | Wait for the next poll. The sensors are now created automatically when it comes back |
| The Energy dashboard looks **empty** | Statistics are only compiled at the top of the hour | Wait for the next full hour. Make sure you picked **Total energy**, not the daily sensor |
| Values of one inverter are **unknown** | The cloud failed to answer for that inverter | It recovers by itself on the next poll. Enable debug logging for `custom_components.rockcore` to see why |

---

## 🧠 How it works

The RC-C app is a thin React Native shell around the web app at
`https://app.rc-ess.com/login/app/26`, which talks to a JowoIoT backend under
`/jowoiot-proxy/api/project/rc`. This integration speaks the same protocol, with read-only requests.

| Endpoint | Purpose |
| --- | --- |
| `POST /auth/login` | `{channelType, content, password, type}` → JWT + numeric owner id |
| `POST /station/overview/searchStation` | All plants with power and energy counters |
| `GET /station/item/show/{id}` | Live summary of one plant |
| `GET /station/item/info/{id}` | Static plant configuration (not used at the moment) |
| `POST /station/item/page` | Inverters of a plant, with power and daily yield |
| `GET /device/data/{id}` | Energy counters of one inverter |
| `GET /device/detail/{id}` | Grid voltage/frequency, temperature, Wi-Fi and the MPPT inputs |
| `POST /alarm-notice-set/pageByAreaId` | Open alarms. The only variant that filters `recovered` server-side |
| `POST /alarm-notice-set/page` | Alarm history. `orderByField` only accepts `0` (time) |

### 🧩 Header quirks

All of them are load-bearing:

- 🏷️ `POST /auth/login` needs an `oem: rc` header to pick the tenant. Without it the login fails with
  `code 500 / "Not a null user"`, which looks like a credentials error but is not.
- 🪪 Every authenticated request needs **both** `Authorization: Bearer <jwt>` and an `OwnerId` header.
  Without the latter the backend answers `400 / "Ownerid in http header can't be null"`.
- 🔑 A rejected password comes back as **HTTP 200 with `code: 500`**, while an expired token gives a
  bare **401**. They are handled differently: a 401 triggers a silent re-login and one retry, while
  a rejected password is never retried.

### 📐 Units

Energy counters arrive in whole watt-hours and are converted to kWh. The eco counters arrive in
tonnes and are converted to kg.

---

## 📝 Changelog

See [CHANGELOG.md](CHANGELOG.md) for the full list of changes, version by version.

---

## 📄 License

Released under the MIT license, see [LICENSE](LICENSE).
