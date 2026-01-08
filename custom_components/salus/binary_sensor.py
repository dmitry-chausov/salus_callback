"""Support for binary (door/window/smoke/leak) sensors."""
from datetime import timedelta
import logging
import async_timeout
import asyncio

import voluptuous as vol
from homeassistant.components.binary_sensor import PLATFORM_SCHEMA, BinarySensorEntity

from homeassistant.const import (
    CONF_HOST,
    CONF_TOKEN
)

import homeassistant.helpers.config_validation as cv
from homeassistant.helpers.update_coordinator import DataUpdateCoordinator, UpdateFailed

from .const import DOMAIN

_LOGGER = logging.getLogger(__name__)

PLATFORM_SCHEMA = PLATFORM_SCHEMA.extend(
    {
        vol.Required(CONF_HOST): cv.string,
        vol.Required(CONF_TOKEN): cv.string,
    }
)


async def async_setup_entry(hass, config_entry, async_add_entities):
    """Set up Salus binary sensors from a config entry."""

    gateway = hass.data[DOMAIN][config_entry.entry_id]

    # Per-gateway cache to avoid duplicate polls
    gateway_cache = {"data": None, "time": None}
    gateway_lock = asyncio.Lock()

    async def get_cached_sensors():
        """Get all sensors with caching to avoid duplicate gateway polls."""
        import time

        async with gateway_lock:
            # Use cached data if less than 1 second old
            if (gateway_cache["data"] is not None and
                gateway_cache["time"] is not None and
                time.time() - gateway_cache["time"] < 1.0):
                return gateway_cache["data"]

            # Fetch new data
            async with async_timeout.timeout(10):
                await gateway.poll_status()
                all_sensors = gateway.get_binary_sensor_devices()
                gateway_cache["data"] = all_sensors
                gateway_cache["time"] = time.time()
                return all_sensors

    async def async_update_data_sw600():
        """Fetch data from API endpoint for SW600 sensors (window/door sensors)."""
        all_sensors = await get_cached_sensors()
        # Filter only SW600 sensors
        return {idx: sensor for idx, sensor in all_sensors.items()
                if sensor.model == "SW600"}

    async def async_update_data_other():
        """Fetch data from API endpoint for other binary sensors."""
        all_sensors = await get_cached_sensors()
        # Filter non-SW600 sensors
        return {idx: sensor for idx, sensor in all_sensors.items()
                if sensor.model != "SW600"}

    # Coordinator for SW600 sensors with 3 second polling
    coordinator_sw600 = DataUpdateCoordinator(
        hass,
        _LOGGER,
        config_entry=config_entry,
        name="sensor_sw600",
        update_method=async_update_data_sw600,
        update_interval=timedelta(seconds=3),
    )

    # Coordinator for other binary sensors with 30 second polling
    coordinator_other = DataUpdateCoordinator(
        hass,
        _LOGGER,
        config_entry=config_entry,
        name="sensor_other",
        update_method=async_update_data_other,
        update_interval=timedelta(seconds=30),
    )

    # Fetch initial data so we have data when entities subscribe
    await coordinator_sw600.async_refresh()
    await coordinator_other.async_refresh()

    # Add SW600 sensors with fast polling
    async_add_entities(SalusBinarySensor(coordinator_sw600, idx, gateway) for idx
                       in coordinator_sw600.data)

    # Add other binary sensors with normal polling
    async_add_entities(SalusBinarySensor(coordinator_other, idx, gateway) for idx
                       in coordinator_other.data)


async def async_setup_platform(hass, config, async_add_entities, discovery_info=None):
    """Set up the binary_sensor platform."""
    pass


class SalusBinarySensor(BinarySensorEntity):
    """Representation of a binary sensor."""

    def __init__(self, coordinator, idx, gateway):
        """Initialize the sensor."""
        self._coordinator = coordinator
        self._idx = idx
        self._gateway = gateway

    async def async_update(self):
        """Update the entity.
        Only used by the generic entity update service.
        """
        await self._coordinator.async_request_refresh()

    async def async_added_to_hass(self):
        """When entity is added to hass."""
        self.async_on_remove(
            self._coordinator.async_add_listener(self.async_write_ha_state)
        )

    @property
    def available(self):
        """Return if entity is available."""
        return self._coordinator.data.get(self._idx).available

    @property
    def device_info(self):
        """Return the device info."""
        return {
            "name": self._coordinator.data.get(self._idx).name,
            "identifiers": {("salus", self._coordinator.data.get(self._idx).unique_id)},
            "manufacturer": self._coordinator.data.get(self._idx).manufacturer,
            "model": self._coordinator.data.get(self._idx).model,
            "sw_version": self._coordinator.data.get(self._idx).sw_version
        }

    @property
    def unique_id(self):
        """Return the unique id."""
        return self._coordinator.data.get(self._idx).unique_id

    @property
    def should_poll(self):
        """No need to poll. Coordinator notifies entity of updates."""
        return False

    @property
    def name(self):
        """Return the name of the sensor."""
        return self._coordinator.data.get(self._idx).name

    @property
    def is_on(self):
        """Return the state of the sensor."""
        return self._coordinator.data.get(self._idx).is_on

    @property
    def device_class(self):
        """Return the device class of the sensor."""
        return self._coordinator.data.get(self._idx).device_class
