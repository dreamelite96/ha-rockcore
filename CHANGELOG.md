# 📝 Changelog

All notable changes to this project are documented in this file.

The format follows [Keep a Changelog](https://keepachangelog.com/en/1.1.0/) and the project uses
[Semantic Versioning](https://semver.org/).

## [1.3.0] - 2026-11-06

### 🔐 Fixed
- **Token race.** When the token expired, every concurrent request logged in again on its own and a
  request could go out as `Bearer None`, which triggered a spurious re-authentication prompt. All
  concurrent requests now share a single re-login.
- **Unreadable cloud answers.** An HTML page (for example a maintenance page) or a JSON body that is
  not an object used to crash the setup with an unhandled error. They are now reported as a normal
  connection error, so Home Assistant retries later.
- **One inverter taking everything down.** A single inverter failing used to make the whole plant
  unavailable. Now only that inverter's values read as unknown until the next poll.
- **Unavailable entities.** Reading the attributes of an entity whose plant or inverter had
  disappeared from the account could raise a `KeyError`.

### 🆕 Added
- **Entities created on the fly.** Plants, inverters and MPPT inputs that show up after startup get
  their entities automatically, with no reload. Example: an inverter that was offline when Home
  Assistant started used to have no PV sensors until the next restart.
- `active_alarms_truncated` attribute on the alarm binary sensors.
- This changelog.

### ⚡ Improved
- **Fewer cloud requests.** The 7-day alarm history, by far the heaviest call, is now refreshed every
  15 minutes instead of on every poll. A poll costs `2 + 2 × plants + 2 × inverters` requests.
- **Larger alarm window.** Up to 10 pages of alarms are read (it was 5), so busy plants are no
  longer cut short.
- **Quieter log.** The "alarm list may be truncated" warning is logged once instead of on every poll.
- **Alarm attributes.** The `active_alarms` list is capped at 25 entries to stay under Home
  Assistant's attribute size limit. The counts still cover every open alarm.
- **Timezone header.** It is computed on every request, so it follows daylight saving changes
  without reloading the integration. The config flow now sends it too.

### 🛡️ Security
- Ids returned by the cloud are URL-quoted before being placed in a request path.
- The CI workflow runs with a read-only token (`permissions: contents: read`).

### 🧹 Changed
- **Requires Home Assistant 2025.1.0 or newer** (it was 2024.11.0).
- Removed an unused request made at startup (the static plant configuration).
- Switched to `AddEntitiesCallback`, which exists in every Home Assistant version.
- Rewrote the code comments and the README for clarity.
- The manifest, the issue tracker and the installation instructions now point to this repository.
