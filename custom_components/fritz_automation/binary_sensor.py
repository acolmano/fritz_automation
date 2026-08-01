"""Binary sensor platform for the FRITZ!Box automation integration."""

from __future__ import annotations

from datetime import datetime
from typing import Any

from homeassistant.components.binary_sensor import BinarySensorDeviceClass, BinarySensorEntity
from homeassistant.config_entries import ConfigEntry
from homeassistant.core import HomeAssistant
from homeassistant.helpers import device_registry as dr
from homeassistant.helpers.entity_platform import AddConfigEntryEntitiesCallback
from homeassistant.helpers.update_coordinator import CoordinatorEntity

from .const import DOMAIN
from .sensor import FritzBoxWanInfoUpdateCoordinator


async def async_setup_entry(
    hass: HomeAssistant,
    config_entry: ConfigEntry,
    async_add_entities: AddConfigEntryEntitiesCallback,
) -> None:
    """Set up the WAN availability binary sensor."""
    coordinator: FritzBoxWanInfoUpdateCoordinator | None = getattr(
        config_entry.runtime_data, "wan_info_coordinator", None
    )

    if coordinator is None:
        coordinator = FritzBoxWanInfoUpdateCoordinator(hass, config_entry)
        await coordinator.async_config_entry_first_refresh()
        setattr(config_entry.runtime_data, "wan_info_coordinator", coordinator)

    async_add_entities(
        [FritzBoxInternetConnectionBinarySensor(coordinator, config_entry)],
        True,
    )


class FritzBoxInternetConnectionBinarySensor(
    CoordinatorEntity[FritzBoxWanInfoUpdateCoordinator], BinarySensorEntity
):
    """Binary sensor reporting whether at least one WAN path is active."""

    def __init__(
        self,
        coordinator: FritzBoxWanInfoUpdateCoordinator,
        config_entry: ConfigEntry,
    ) -> None:
        """Initialize the binary sensor."""
        super().__init__(coordinator)
        self._config_entry = config_entry
        self._attr_unique_id = f"{config_entry.entry_id}_internet_connection_active"
        self._attr_name = "Fritz Automation Internet Connection Active"
        self.entity_id = "binary_sensor.fritz_automation_internet_connection_active"
        self._attr_device_class = BinarySensorDeviceClass.CONNECTIVITY

        self._attr_device_info = dr.DeviceInfo(
            identifiers={(DOMAIN, config_entry.entry_id)},
            name="Fritz Automation",
            configuration_url=f"http://{config_entry.data['host']}/",
        )

    @property
    def is_on(self) -> bool:
        """Return True when at least one internet connection is active."""
        if not self.coordinator.data:
            return False
        return bool(self.coordinator.data.get("internet_connection_active", False))

    @property
    def extra_state_attributes(self) -> dict[str, Any] | None:
        """Return additional WAN attributes for diagnostics."""
        if not self.coordinator.data:
            return None
        return {
            "connection_type": self.coordinator.data.get("connection_type"),
            "access_technology": self.coordinator.data.get("access_technology"),
            "dsl_link_state": self.coordinator.data.get("dsl_link_state"),
            "lte_link_state": self.coordinator.data.get("lte_link_state"),
            "wan_failover_active": self.coordinator.data.get("wan_failover_active"),
            "source": "TR-064 WAN info coordinator",
            "last_updated": datetime.now().isoformat(),
        }
