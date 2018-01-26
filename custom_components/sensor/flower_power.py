from homeassistant.helpers.entity import Entity
from homeassistant.const import TEMP_CELSIUS
from homeassistant.components.sensor import PLATFORM_SCHEMA
import voluptuous as vol
import homeassistant.helpers.config_validation as cv
import logging
import asyncio
from homeassistant.helpers.aiohttp_client import async_get_clientsession
import async_timeout
import aiohttp
from homeassistant.exceptions import PlatformNotReady


import requests
from pprint import pformat  # here only for aesthetic

PLATFORM_SCHEMA = PLATFORM_SCHEMA.extend({
    vol.Required('username'): cv.string,
    vol.Required('password'): cv.string,
    vol.Required('clientid'): cv.string,
    vol.Required('clientsecret'): cv.string
})

REQUEST_TIMEOUT = 5  # In seconds; argument to asyncio.timeout
DEFAULT_ENDPOINT = 'https://api-flower-power-pot.parrot.com/{uri}'
AUTHENTICATION_ENDPOINT = 'user/v1/authenticate'
PROFILE_ENDPOINT = 'user/v4/profile'
GARDEN_ENDPOINT = 'garden/v1/status'

_LOGGER = logging.getLogger(__name__)

class SensorRequestError(Exception):
    """Error to indicate a CityBikes API request has failed."""

    pass


@asyncio.coroutine
def async_setup_platform(hass, config, async_add_devices, discovery_info=None):

    # First we set our credentials
    username = config.get('username')
    password = config.get('password')

    # From the developer portal
    client_id = config.get('clientid')
    client_secret = config.get('clientsecret')

    session = async_get_clientsession(hass)

    with async_timeout.timeout(REQUEST_TIMEOUT, loop=hass.loop):
        req = yield from session.get(DEFAULT_ENDPOINT.format(uri=AUTHENTICATION_ENDPOINT),
                           data={'grant_type': 'password',
                                 'username': username,
                                 'password': password,
                                 'client_id': client_id,
                                 'client_secret': client_secret,
                                })

    response = yield from req.json()

    access_token = response['access_token']
    _LOGGER.debug("Authentication successful")
    HEADERS = {'Authorization': 'Bearer {token}'.format(token=access_token)}

    with async_timeout.timeout(REQUEST_TIMEOUT, loop=hass.loop):
        req = yield from session.get(DEFAULT_ENDPOINT.format(uri=GARDEN_ENDPOINT),
                       headers=HEADERS)

    _LOGGER.debug("Fetched data for devices")
    response = yield from req.json()

    locations = response['locations']
    _LOGGER.debug("Setting up devices")

    devices = []

    for location in locations:
        location_id = location['location_identifier']
        light = location['light']['gauge_values']['current_value']
        devices.append(FlowerPowerSensor(hass, light, 'lux', 'Flower power light sensor', 'light', location_id, HEADERS))

        air_temperature = location['air_temperature']['gauge_values']['current_value']
        devices.append(FlowerPowerSensor(hass, air_temperature, TEMP_CELSIUS, 'Flower power temperature sensor', 'air_temperature', location_id, HEADERS))

        fertilizer = location['fertilizer']['gauge_values']['current_value']
        devices.append(FlowerPowerSensor(hass, fertilizer, 'dS/m', 'Flower power fertilizer sensor', 'fertilizer', location_id, HEADERS))

        watering = location['watering']['automatic_watering']['gauge_values']['current_value']
        devices.append(FlowerPowerSensor(hass, watering, '%', 'Flower power watering sensor', 'automatic_watering', location_id, HEADERS))

        soil_moisture = location['watering']['soil_moisture']['gauge_values']['current_value']
        devices.append(FlowerPowerSensor(hass, soil_moisture, '%', 'Flower power humidity sensor', 'soil_moisture', location_id, HEADERS))

    _LOGGER.debug("Set up successful")
    async_add_devices(devices, True)

@asyncio.coroutine
def async_sensor_request(hass, location_id, sensor_type, HEADERS):
    """Perform a request to Flower power API endpoint, and parse the response."""

    session = async_get_clientsession(hass)

    with async_timeout.timeout(REQUEST_TIMEOUT, loop=hass.loop):
        req = yield from session.get(DEFAULT_ENDPOINT.format(uri=GARDEN_ENDPOINT),
                       headers=HEADERS)

    response = yield from req.json()

    locations = response['locations']

    for location in locations:
        if location['location_identifier'] == location_id:
            if sensor_type == 'light':
                return location['light']['gauge_values']['current_value']
            elif sensor_type == 'air_temperature':
                return location['air_temperature']['gauge_values']['current_value']
            elif sensor_type == 'fertilizer':
                return location['fertilizer']['gauge_values']['current_value']
            elif sensor_type == 'automatic_watering':
                return location['watering']['automatic_watering']['gauge_values']['current_value']
            elif sensor_type == 'soil_moisture':
                return location['watering']['soil_moisture']['gauge_values']['current_value']

    return 0


class FlowerPowerSensor(Entity):
    """Representation of a Sensor."""

    def __init__(self, hass, state, unit_of_measurement, name, sensor_type, location_id, HEADERS):
        """Initialize the sensor."""
        self.hass = hass
        self._state = state
        self._unit_of_measurement = unit_of_measurement
        self._name = name
        self._sensor_type = sensor_type
        self._location_id = location_id
        self._HEADERS = HEADERS
        self.ready = asyncio.Event()

    @property
    def name(self):
        """Return the name of the sensor."""
        return self._name

    @property
    def state(self):
        """Return the state of the sensor."""
        return self._state

    @property
    def unit_of_measurement(self):
        """Return the unit of measurement."""
        return self._unit_of_measurement

    @asyncio.coroutine
    def async_update(self):
        _LOGGER.debug("Trying to update the sensor")
        if self.ready.is_set():
            _LOGGER.debug("Sensor ready!")
            with async_timeout.timeout(REQUEST_TIMEOUT, loop=self.hass.loop):
                req = yield from async_sensor_request(self.hass, self._location_id, self._sensor_type, self._HEADERS)

            _LOGGER.debug("New value for sensor %s : %s", self._name, req)
            self._state = req

        else:
            _LOGGER.debug("Sensor not ready")
            self.ready.set()
        """Fetch new state data for the sensor.

        This is the only method that should fetch new data for Home Assistant.
        """
