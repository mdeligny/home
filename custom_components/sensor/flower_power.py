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
from datetime import datetime, timedelta

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
GARDEN_STATUS_ENDPOINT = 'garden/v1/status'
GARDEN_CONFIGURATION_ENDPOINT = 'garden/v2/configuration'
LOCATION_SAMPLE_ENDPOINT = 'sensor_data/v6/sample/location/{location_id}?from_datetime_utc={from_datetime_utc}&to_datetime_utc={to_datetime_utc}'

_LOGGER = logging.getLogger(__name__)

def format_light_value(light):
    """Do a simple conversion to have lux data."""
    return round(light*14000/3)

@asyncio.coroutine
def get_authentication_token(hass, credentials):
    """Connect to Flower Power API with credentials (username, password, clientid and clientsecret), and extract access_token."""
    session = async_get_clientsession(hass)

    with async_timeout.timeout(REQUEST_TIMEOUT, loop=hass.loop):
        req = yield from session.get(DEFAULT_ENDPOINT.format(uri=AUTHENTICATION_ENDPOINT),
                           data=credentials)

    response = yield from req.json()
    return response['access_token']

@asyncio.coroutine
def get_location_samples(hass, location_id, HEADERS):
    """Get last 10 days samples data for a dedicated location."""
    session = async_get_clientsession(hass)

    to_datetime_utc = datetime.utcnow()
    from_datetime_utc = to_datetime_utc - timedelta(10)

    with async_timeout.timeout(REQUEST_TIMEOUT, loop=hass.loop):
        req = yield from session.get(DEFAULT_ENDPOINT.format(uri=LOCATION_SAMPLE_ENDPOINT.format(location_id=location_id,from_datetime_utc=from_datetime_utc,to_datetime_utc=to_datetime_utc)),
                       headers=HEADERS)

    response = yield from req.json()
    return response['samples']

@asyncio.coroutine
def get_garden_configuration(hass, HEADERS):
    """Get a list of locations for the garden configuration."""
    session = async_get_clientsession(hass)

    with async_timeout.timeout(REQUEST_TIMEOUT, loop=hass.loop):
        req = yield from session.get(DEFAULT_ENDPOINT.format(uri=GARDEN_CONFIGURATION_ENDPOINT),
                       headers=HEADERS)

    response = yield from req.json()
    return response['locations']

@asyncio.coroutine
def get_devices_to_sync(hass, locations, HEADERS):
    """Get a formatted list of devices for all locations of the garden."""
    devices = []

    for location in locations:
        location_id = location['location_identifier']
        samples = yield from get_location_samples(hass, location_id, HEADERS)

        if samples:
            latest_sample = samples[-1]
            location_data = {
                'last_update' : latest_sample['capture_datetime_utc'],
                'location_id' : location_id,
                'plant_nickname' : location['plant_nickname'],
                'is_indoor' : location['is_indoor'],
                'in_pot' : location['in_pot'],
                'longitude' : location['longitude'],
                'latitude' : location['latitude']
            }

            if latest_sample['light']:
                light = format_light_value(latest_sample['light'])
                devices.append(FlowerPowerSensor(hass, light, 'lux', 'light sensor', 'light', location_data, HEADERS))

            if latest_sample['air_temperature_celsius']:
                air_temperature = round(latest_sample['air_temperature_celsius'],1)
                devices.append(FlowerPowerSensor(hass, air_temperature, TEMP_CELSIUS, 'temperature sensor', 'air_temperature', location_data, HEADERS))

            if latest_sample['fertilizer_level']:
                fertilizer = round(latest_sample['fertilizer_level'],1)
                devices.append(FlowerPowerSensor(hass, fertilizer, 'dS/m', 'fertilizer sensor', 'fertilizer', location_data, HEADERS))

            if latest_sample['water_tank_level_percent']:
                watering = round(latest_sample['water_tank_level_percent'])
                devices.append(FlowerPowerSensor(hass, watering, '%', 'watering sensor', 'automatic_watering', location_data, HEADERS))

            if latest_sample['soil_moisture_percent']:
                soil_moisture = round(latest_sample['soil_moisture_percent'])
                devices.append(FlowerPowerSensor(hass, soil_moisture, '%', 'humidity sensor', 'soil_moisture', location_data, HEADERS))

            if latest_sample['battery_percent']:
                battery = round(latest_sample['battery_percent'])
                devices.append(FlowerPowerSensor(hass, battery, '%', 'battery level', 'battery', location_data, HEADERS))

    return devices

@asyncio.coroutine
def async_setup_platform(hass, config, async_add_devices, discovery_info=None):
    """Set up the platform."""
    credentials = {
        'grant_type': 'password',
        'username' : config.get('username'),
        'password' : config.get('password'),
        'client_id' : config.get('clientid'),
        'client_secret' : config.get('clientsecret')
    }

    access_token = yield from get_authentication_token(hass, credentials)
    HEADERS = {'Authorization': 'Bearer {token}'.format(token=access_token)}

    locations = yield from get_garden_configuration(hass, HEADERS)
    devices = yield from get_devices_to_sync(hass, locations, HEADERS)

    async_add_devices(devices, True)

@asyncio.coroutine
def async_device_request(hass, location_id, sensor_type, HEADERS):
    """Get new value for a device."""
    samples = yield from get_location_samples(hass, location_id, HEADERS)
    data = {
        'state' : 0
    }

    if samples:
        latest_sample = samples[-1]
        data['capture_datetime_utc'] = latest_sample['capture_datetime_utc']

        data['state'] = {
            'light': format_light_value(latest_sample['light']),
            'air_temperature': round(latest_sample['air_temperature_celsius'],1),
            'fertilizer': round(latest_sample['fertilizer_level'],1),
            'automatic_watering': round(latest_sample['water_tank_level_percent']),
            'soil_moisture': round(latest_sample['soil_moisture_percent']),
            'battery': round(latest_sample['battery_percent'])
        }[sensor_type]

    return data

class FlowerPowerSensor(Entity):
    """Representation of a Sensor."""

    def __init__(self, hass, state, unit_of_measurement, name, sensor_type, data, HEADERS):
        """Initialize the sensor."""
        self.hass = hass
        self._state = state
        self._unit_of_measurement = unit_of_measurement
        self._base_name = name
        self._sensor_type = sensor_type
        self._HEADERS = HEADERS
        self._data = data
        self.ready = asyncio.Event()

    @property
    def name(self):
        """Return the name of the sensor."""
        if self._data['plant_nickname']:
            return "{} {}".format(self._data['plant_nickname'], self._base_name)
        return self._base_name

    @property
    def state(self):
        """Return the state of the sensor."""
        return self._state

    @property
    def unit_of_measurement(self):
        """Return the unit of measurement."""
        return self._unit_of_measurement

    @property
    def icon(self):
        """Return the icon to display."""
        return {
            'light': 'mdi:weather-sunny',
            'air_temperature': 'mdi:thermometer',
            'fertilizer': 'mdi:fuel',
            'automatic_watering': 'mdi:cup-water',
            'soil_moisture': 'mdi:water-percent',
            'battery': 'mdi:battery'
        }[self._sensor_type]

    @property
    def device_state_attributes(self):
        """Return the state attributes of the last update."""
        return self._data

    @asyncio.coroutine
    def async_update(self):
        """Fetch new state data for the sensor."""
        _LOGGER.debug("Trying to update the sensor")
        if self.ready.is_set():
            with async_timeout.timeout(REQUEST_TIMEOUT, loop=self.hass.loop):
                response = yield from async_device_request(self.hass, self._data['location_id'], self._sensor_type, self._HEADERS)

            self._state = response['state']

            if response['capture_datetime_utc']:
                self._data['last_update'] = response['capture_datetime_utc']

            _LOGGER.debug("New value for sensor %s : %s", self._base_name, response['state'])

        else:
            _LOGGER.debug("Sensor not ready")
            self.ready.set()
