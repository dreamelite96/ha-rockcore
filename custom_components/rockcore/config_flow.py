"""🧙 Config flow for the Rockcore Solar (RC-C) integration."""

from __future__ import annotations

from collections.abc import Mapping
import logging
from typing import Any

import voluptuous as vol

from homeassistant.config_entries import (
    ConfigFlow,
    ConfigFlowResult,
    OptionsFlow,
)
from homeassistant.const import CONF_EMAIL, CONF_PASSWORD
from homeassistant.core import callback
from homeassistant.helpers.aiohttp_client import async_get_clientsession
from homeassistant.helpers.selector import (
    NumberSelector,
    NumberSelectorConfig,
    NumberSelectorMode,
    TextSelector,
    TextSelectorConfig,
    TextSelectorType,
)

from .api import RockcoreAuthError, RockcoreClient, RockcoreError
from .const import (
    CONF_SCAN_INTERVAL,
    DEFAULT_SCAN_INTERVAL,
    DOMAIN,
    MAX_SCAN_INTERVAL,
    MIN_SCAN_INTERVAL,
)
from .coordinator import RockcoreConfigEntry
from .util import timezone_offset_hours

_LOGGER = logging.getLogger(__name__)

#: 📝 The form shown on first setup: the same account used in the RC-C app.
STEP_USER_SCHEMA = vol.Schema(
    {
        vol.Required(CONF_EMAIL): TextSelector(
            TextSelectorConfig(type=TextSelectorType.EMAIL, autocomplete="username")
        ),
        vol.Required(CONF_PASSWORD): TextSelector(
            TextSelectorConfig(type=TextSelectorType.PASSWORD, autocomplete="current-password")
        ),
    }
)


class RockcoreConfigFlow(ConfigFlow, domain=DOMAIN):
    """🧙 Handle the Rockcore Solar config flow (setup and re-authentication)."""

    VERSION = 1

    async def _async_validate(self, email: str, password: str) -> tuple[RockcoreClient, str]:
        """🔐 Log in and return the client plus the account id."""
        client = RockcoreClient(
            async_get_clientsession(self.hass),
            email,
            password,
            timezone_offset=timezone_offset_hours,
        )
        await client.async_login()
        return client, client.user_id or email

    # ── 🆕 First setup ───────────────────────────────────────────────────────

    async def async_step_user(
        self, user_input: dict[str, Any] | None = None
    ) -> ConfigFlowResult:
        """Handle the initial step: ask for the credentials and check them."""
        errors: dict[str, str] = {}

        if user_input is not None:
            email = user_input[CONF_EMAIL].strip()
            password = user_input[CONF_PASSWORD]
            try:
                client, account_id = await self._async_validate(email, password)
            except RockcoreAuthError as err:
                # ⚠️ The cloud locks the account after ten bad passwords, so the
                # error text shown to the user warns about it (see strings.json).
                _LOGGER.debug("Rockcore rejected the credentials: %s", err)
                errors["base"] = "invalid_auth"
            except RockcoreError:
                errors["base"] = "cannot_connect"
            else:
                # 🆔 One entry per cloud account.
                await self.async_set_unique_id(account_id)
                self._abort_if_unique_id_configured()
                return self.async_create_entry(
                    title=client.user_name or email,
                    data={CONF_EMAIL: email, CONF_PASSWORD: password},
                )

        return self.async_show_form(
            step_id="user", data_schema=STEP_USER_SCHEMA, errors=errors
        )

    # ── 🔁 Re-authentication ─────────────────────────────────────────────────

    async def async_step_reauth(
        self, entry_data: Mapping[str, Any]
    ) -> ConfigFlowResult:
        """Handle re-authentication after the credentials stopped working."""
        return await self.async_step_reauth_confirm()

    async def async_step_reauth_confirm(
        self, user_input: dict[str, Any] | None = None
    ) -> ConfigFlowResult:
        """Ask for the password again (the e-mail is already known)."""
        errors: dict[str, str] = {}
        entry = self._get_reauth_entry()

        if user_input is not None:
            password = user_input[CONF_PASSWORD]
            try:
                await self._async_validate(entry.data[CONF_EMAIL], password)
            except RockcoreAuthError:
                errors["base"] = "invalid_auth"
            except RockcoreError:
                errors["base"] = "cannot_connect"
            else:
                return self.async_update_reload_and_abort(
                    entry, data_updates={CONF_PASSWORD: password}
                )

        return self.async_show_form(
            step_id="reauth_confirm",
            data_schema=vol.Schema(
                {
                    vol.Required(CONF_PASSWORD): TextSelector(
                        TextSelectorConfig(
                            type=TextSelectorType.PASSWORD, autocomplete="current-password"
                        )
                    )
                }
            ),
            description_placeholders={CONF_EMAIL: entry.data[CONF_EMAIL]},
            errors=errors,
        )

    # ── ⚙️ Options ───────────────────────────────────────────────────────────

    @staticmethod
    @callback
    def async_get_options_flow(entry: RockcoreConfigEntry) -> RockcoreOptionsFlow:
        """Return the options flow."""
        return RockcoreOptionsFlow()


class RockcoreOptionsFlow(OptionsFlow):
    """⚙️ Handle the Rockcore Solar options (the polling interval)."""

    async def async_step_init(
        self, user_input: dict[str, Any] | None = None
    ) -> ConfigFlowResult:
        """Let the user change the polling interval."""
        if user_input is not None:
            return self.async_create_entry(
                data={CONF_SCAN_INTERVAL: int(user_input[CONF_SCAN_INTERVAL])}
            )

        current = self.config_entry.options.get(
            CONF_SCAN_INTERVAL, int(DEFAULT_SCAN_INTERVAL.total_seconds())
        )
        return self.async_show_form(
            step_id="init",
            data_schema=vol.Schema(
                {
                    vol.Required(CONF_SCAN_INTERVAL, default=current): NumberSelector(
                        NumberSelectorConfig(
                            min=MIN_SCAN_INTERVAL,
                            max=MAX_SCAN_INTERVAL,
                            step=10,
                            unit_of_measurement="s",
                            mode=NumberSelectorMode.BOX,
                        )
                    )
                }
            ),
        )
