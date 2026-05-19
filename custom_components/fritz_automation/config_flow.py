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
from homeassistant.helpers.selector import (
    SelectOptionDict,
    SelectSelector,
    SelectSelectorConfig,
)

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

_MANUAL = "__manual__"


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

    def _get_mobile_devices(self) -> list[dict] | None:
        """Return devices from sensor.mobile_devices_info, or None if unavailable."""
        state = self.hass.states.get("sensor.mobile_devices_info")
        if state is None:
            return None
        return state.attributes.get("devices", [])

    def _build_selector_schema(self, devices: list[dict]) -> vol.Schema:
        """Build device dropdown schema from MDI device list."""
        options: list[SelectOptionDict] = [
            {"value": _MANUAL, "label": "Inserisci manualmente"},
        ]
        for device in devices:
            name = device.get("name") or ""
            if not name:
                continue
            phone = device.get("phone_number") or ""
            label = f"{name} ({phone})" if phone else name
            options.append({"value": name, "label": label})
        return vol.Schema(
            {vol.Required("device_selector"): SelectSelector(SelectSelectorConfig(options=options))}
        )

    # ── ADD FLOW ──────────────────────────────────────────────────────────────

    async def async_step_user(
        self, user_input: dict[str, Any] | None = None
    ) -> SubentryFlowResult:
        """Step 1 (add): select device from MDI, or skip to manual entry."""
        devices = self._get_mobile_devices()

        if devices is None:
            # MDI not available – go straight to manual entry
            return await self.async_step_details()

        if user_input is not None:
            selected = user_input["device_selector"]
            if selected == _MANUAL:
                self._prefill: dict[str, str] = {}
            else:
                matched = next((d for d in devices if d.get("name") == selected), None)
                self._prefill = {CONF_NAME: selected}
                if matched and matched.get("phone_number"):
                    self._prefill[CONF_TARGET] = matched["phone_number"]
            return await self.async_step_details()

        return self.async_show_form(
            step_id="user",
            data_schema=self._build_selector_schema(devices),
        )

    async def async_step_details(
        self, user_input: dict[str, Any] | None = None
    ) -> SubentryFlowResult:
        """Step 2 (add): enter / confirm target name and phone number."""
        errors: dict[str, str] = {}

        if user_input is not None:
            try:
                phonenumbers.parse(user_input[CONF_TARGET])
            except phonenumbers.NumberParseException:
                errors[CONF_TARGET] = "impossible_number"
            else:
                return self.async_create_entry(
                    title=user_input[CONF_NAME],
                    data=user_input,
                )

        fill_data = user_input if user_input is not None else getattr(self, "_prefill", {})

        schema = vol.Schema({vol.Required(CONF_NAME): str, vol.Required(CONF_TARGET): str})
        if fill_data:
            schema = self.add_suggested_values_to_schema(schema, fill_data)

        return self.async_show_form(
            step_id="details",
            data_schema=schema,
            errors=errors,
        )

    # ── RECONFIGURE FLOW ──────────────────────────────────────────────────────

    async def async_step_reconfigure(
        self, user_input: dict[str, Any] | None = None
    ) -> SubentryFlowResult:
        """Reconfigure step 1: select new device from MDI or keep current."""
        devices = self._get_mobile_devices()

        if devices is None:
            # MDI not available – go straight to details with existing values
            return await self.async_step_reconfigure_details()

        if user_input is not None:
            selected = user_input["device_selector"]
            config_subentry = self._get_reconfigure_subentry()
            if selected == _MANUAL:
                self._prefill = {
                    CONF_NAME: config_subentry.data.get(CONF_NAME, ""),
                    CONF_TARGET: config_subentry.data.get(CONF_TARGET, ""),
                }
            else:
                matched = next((d for d in devices if d.get("name") == selected), None)
                self._prefill = {CONF_NAME: selected}
                if matched and matched.get("phone_number"):
                    self._prefill[CONF_TARGET] = matched["phone_number"]
            return await self.async_step_reconfigure_details()

        return self.async_show_form(
            step_id="reconfigure",
            data_schema=self._build_selector_schema(devices),
        )

    async def async_step_reconfigure_details(
        self, user_input: dict[str, Any] | None = None
    ) -> SubentryFlowResult:
        """Reconfigure step 2: update target name and phone number."""
        config_entry = self._get_entry()
        config_subentry = self._get_reconfigure_subentry()
        errors: dict[str, str] = {}

        if user_input is not None:
            try:
                phonenumbers.parse(user_input[CONF_TARGET])
            except phonenumbers.NumberParseException:
                errors[CONF_TARGET] = "impossible_number"
            else:
                return self.async_update_and_abort(
                    entry=config_entry,
                    subentry=config_subentry,
                    title=user_input[CONF_NAME],
                    data_updates=user_input,
                )

        if user_input is not None:
            fill_data = user_input
        else:
            fill_data = getattr(
                self,
                "_prefill",
                {
                    CONF_NAME: config_subentry.data.get(CONF_NAME, ""),
                    CONF_TARGET: config_subentry.data.get(CONF_TARGET, ""),
                },
            )

        schema = self.add_suggested_values_to_schema(
            vol.Schema({vol.Required(CONF_NAME): str, vol.Required(CONF_TARGET): str}),
            fill_data,
        )

        return self.async_show_form(
            step_id="reconfigure_details",
            data_schema=schema,
            errors=errors,
        )
