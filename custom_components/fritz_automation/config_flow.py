"""Config flow for the AVM FRITZ!Box Automation integration."""

from __future__ import annotations

import logging
from typing import Any

import aiohttp
from .fritzbox import FritzBox
import phonenumbers
import voluptuous as vol

from homeassistant.config_entries import (
    ConfigEntry,
    ConfigFlow,
    ConfigFlowResult,
    ConfigSubentryFlow,
    SubentryFlowResult,
)
from homeassistant.const import (
    CONF_HOST,
    CONF_NAME,
    CONF_PASSWORD,
    CONF_TARGET,
    CONF_TOKEN,
    CONF_USERNAME,
)
from homeassistant.core import callback
from homeassistant.helpers.aiohttp_client import async_get_clientsession

from .const import DOMAIN

_LOGGER = logging.getLogger(__name__)

STEP_USER_DATA_SCHEMA = vol.Schema(
    {
        vol.Required(CONF_HOST): str,
        vol.Required(CONF_USERNAME): str,
        vol.Required(CONF_PASSWORD): str,
        vol.Required(CONF_TOKEN): str,
    }
)

STEP_NAME_DATA_SCHEMA = vol.Schema(
    {
        vol.Required(CONF_NAME): str,
    }
)

STEP_TARGET_PHONE_DATA_SCHEMA = vol.Schema(
    {
        vol.Required(CONF_TARGET): str,
    }
)


class FritzBoxConfigFlow(ConfigFlow, domain=DOMAIN):
    """Handle a config flow for AVM FRITZ!Box Automation."""

    VERSION = 1

    async def async_step_user(
        self, user_input: dict[str, Any] | None = None
    ) -> ConfigFlowResult:
        """Handle the initial step."""
        errors: dict[str, str] = {}
        code = ""
        if user_input is not None:
            user_input[CONF_TOKEN] = user_input[CONF_TOKEN].replace(" ", "")
            session = async_get_clientsession(self.hass)
            box = FritzBox(user_input[CONF_HOST], session)
            box.set_otp(user_input[CONF_TOKEN])
            code = box.get_otp()
            try:
                await box.login(user_input[CONF_USERNAME], user_input[CONF_PASSWORD])
                otp_configured = await box.is_otp_configured()
                await box.logout()
                if not otp_configured:
                    errors[CONF_TOKEN] = "invalid_auth"
                else:
                    return self.async_create_entry(
                        title=f"Fritz Automation ({user_input[CONF_HOST]})", data=user_input
                    )
            except aiohttp.client_exceptions.ClientConnectorError:
                errors[CONF_HOST] = "cannot_connect"
            except RuntimeError:
                _LOGGER.exception("Unexpected exception")
                errors["base"] = "unknown"

            data_schema = self.add_suggested_values_to_schema(
                STEP_USER_DATA_SCHEMA, user_input
            )
        else:
            data_schema = STEP_USER_DATA_SCHEMA

        return self.async_show_form(
            step_id="user",
            data_schema=data_schema,
            errors=errors,
            description_placeholders={"code": code},
        )

    @classmethod
    @callback
    def async_get_supported_subentry_types(
        cls, config_entry: ConfigEntry
    ) -> dict[str, type[ConfigSubentryFlow]]:
        """Return subentries supported by this integration."""
        return {"target": TargetSubentryFlowHandler}


class TargetSubentryFlowHandler(ConfigSubentryFlow):
    """Handle subentry flow for adding and modifying a location."""

    def _lookup_phone(self, target_name: str) -> tuple[str | None, bool]:
        """Look up phone number from sensor.mobile_devices_info.

        Returns (phone_number, integration_found).
        phone_number is None if device not found or has no phone number.
        """
        state = self.hass.states.get("sensor.mobile_devices_info")
        if state is None:
            return None, False
        devices = state.attributes.get("devices", [])
        matched = next((d for d in devices if d.get("name") == target_name), None)
        if matched is None:
            return None, True
        return matched.get("phone_number") or None, True

    async def async_step_user(
        self, user_input: dict[str, Any] | None = None
    ) -> SubentryFlowResult:
        """Step 1: collect target name."""
        if user_input is not None:
            self._target_name: str = user_input[CONF_NAME]
            return await self.async_step_target()

        return self.async_show_form(
            step_id="user",
            data_schema=STEP_NAME_DATA_SCHEMA,
        )

    async def async_step_target(
        self, user_input: dict[str, Any] | None = None
    ) -> SubentryFlowResult:
        """Step 2: look up phone from mobile_devices_info and collect target number."""
        errors: dict[str, str] = {}
        phone_note = ""

        phone, integration_found = self._lookup_phone(self._target_name)

        if not integration_found:
            errors["base"] = "mobile_device_info_missing"
        elif phone is None:
            phone_note = "\n\nNessun numero di telefono associabile al device"

        if user_input is not None:
            try:
                phonenumbers.parse(user_input[CONF_TARGET])
            except phonenumbers.NumberParseException:
                errors[CONF_TARGET] = "impossible_number"
            else:
                return self.async_create_entry(
                    title=self._target_name,
                    data={CONF_NAME: self._target_name, CONF_TARGET: user_input[CONF_TARGET]},
                )

        if user_input is not None:
            fill_data = user_input
        elif phone:
            fill_data = {CONF_TARGET: phone}
        else:
            fill_data = {}

        schema = (
            self.add_suggested_values_to_schema(STEP_TARGET_PHONE_DATA_SCHEMA, fill_data)
            if fill_data
            else STEP_TARGET_PHONE_DATA_SCHEMA
        )

        return self.async_show_form(
            step_id="target",
            data_schema=schema,
            errors=errors,
            description_placeholders={
                "target_name": self._target_name,
                "phone_note": phone_note,
            },
        )

    async def async_step_reconfigure(
        self, user_input: dict[str, Any] | None = None
    ) -> SubentryFlowResult:
        """Reconfigure step 1: update target name."""
        config_subentry = self._get_reconfigure_subentry()

        if user_input is not None:
            self._target_name = user_input[CONF_NAME]
            return await self.async_step_reconfigure_target()

        return self.async_show_form(
            step_id="reconfigure",
            data_schema=self.add_suggested_values_to_schema(
                STEP_NAME_DATA_SCHEMA, config_subentry.data
            ),
        )

    async def async_step_reconfigure_target(
        self, user_input: dict[str, Any] | None = None
    ) -> SubentryFlowResult:
        """Reconfigure step 2: look up phone and update target number."""
        config_entry = self._get_entry()
        config_subentry = self._get_reconfigure_subentry()
        errors: dict[str, str] = {}
        phone_note = ""

        phone, integration_found = self._lookup_phone(self._target_name)

        if not integration_found:
            errors["base"] = "mobile_device_info_missing"
        elif phone is None:
            phone_note = "\n\nNessun numero di telefono associabile al device"

        if user_input is not None:
            try:
                phonenumbers.parse(user_input[CONF_TARGET])
            except phonenumbers.NumberParseException:
                errors[CONF_TARGET] = "impossible_number"
            else:
                return self.async_update_and_abort(
                    entry=config_entry,
                    subentry=config_subentry,
                    title=self._target_name,
                    data_updates={CONF_NAME: self._target_name, CONF_TARGET: user_input[CONF_TARGET]},
                )

        if user_input is not None:
            fill_data = user_input
        elif phone:
            fill_data = {CONF_TARGET: phone}
        else:
            fill_data = {CONF_TARGET: config_subentry.data.get(CONF_TARGET, "")}

        schema = self.add_suggested_values_to_schema(STEP_TARGET_PHONE_DATA_SCHEMA, fill_data)

        return self.async_show_form(
            step_id="reconfigure_target",
            data_schema=schema,
            errors=errors,
            description_placeholders={
                "target_name": self._target_name,
                "phone_note": phone_note,
            },
        )
