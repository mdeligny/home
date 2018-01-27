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
GARDEN_ENDPOINT = 'garden/v1/status'
LOCATION_SAMPLE_ENDPOINT = 'sensor_data/v6/sample/location/{location_id}?from_datetime_utc={from_datetime_utc}&to_datetime_utc={to_datetime_utc}'

_LOGGER = logging.getLogger(__name__)

class SensorRequestError(Exception):
    """Error to indicate a CityBikes API request has failed."""

    pass


@asyncio.coroutine
def async_setup_platform(hass, config, async_add_devices, discovery_info=None):

    username = config.get('username')
    password = config.get('password')

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

        to_datetime_utc = datetime.utcnow()
        from_datetime_utc = to_datetime_utc - timedelta(10)

        _LOGGER.debug("fetching data from %s to %s",from_datetime_utc, to_datetime_utc)
        with async_timeout.timeout(REQUEST_TIMEOUT, loop=hass.loop):
            req = yield from session.get(DEFAULT_ENDPOINT.format(uri=LOCATION_SAMPLE_ENDPOINT.format(location_id=location_id,from_datetime_utc=from_datetime_utc,to_datetime_utc=to_datetime_utc)),
                           headers=HEADERS)

        response = yield from req.json()

        latest_sample = response['samples'][-1]

        """ We have to do math about the light captor because Parrot doesn't send correct data"""
        light = round(latest_sample['light']*14000/3)
        devices.append(FlowerPowerSensor(hass, light, 'lux', 'Flower power light sensor', 'light', location_id, HEADERS))

        air_temperature = round(latest_sample['air_temperature_celsius'],1)
        devices.append(FlowerPowerSensor(hass, air_temperature, TEMP_CELSIUS, 'Flower power temperature sensor', 'air_temperature', location_id, HEADERS))

        fertilizer = round(latest_sample['fertilizer_level'],1)
        devices.append(FlowerPowerSensor(hass, fertilizer, 'dS/m', 'Flower power fertilizer sensor', 'fertilizer', location_id, HEADERS))

        watering = round(latest_sample['water_tank_level_percent'])
        devices.append(FlowerPowerSensor(hass, watering, '%', 'Flower power watering sensor', 'automatic_watering', location_id, HEADERS))

        soil_moisture = round(latest_sample['soil_moisture_percent'])
        devices.append(FlowerPowerSensor(hass, soil_moisture, '%', 'Flower power humidity sensor', 'soil_moisture', location_id, HEADERS))

        battery = round(latest_sample['battery_percent'])
        devices.append(FlowerPowerSensor(hass, battery, '%', 'Flower power battery level', 'battery', location_id, HEADERS))

    _LOGGER.debug("Set up successful")
    async_add_devices(devices, True)

@asyncio.coroutine
def async_sensor_request(hass, location_id, sensor_type, HEADERS):
    """Perform a request to Flower power API endpoint, and parse the response."""

    session = async_get_clientsession(hass)

    to_datetime_utc = datetime.utcnow()
    from_datetime_utc = to_datetime_utc - timedelta(10)

    _LOGGER.debug("fetching data from %s to %s",from_datetime_utc, to_datetime_utc)
    with async_timeout.timeout(REQUEST_TIMEOUT, loop=hass.loop):
        req = yield from session.get(DEFAULT_ENDPOINT.format(uri=LOCATION_SAMPLE_ENDPOINT.format(location_id=location_id,from_datetime_utc=from_datetime_utc,to_datetime_utc=to_datetime_utc)),
                       headers=HEADERS)

    response = yield from req.json()

    latest_sample = response['samples'][-1]

    _LOGGER.debug("latest sample was on %s", latest_sample['capture_datetime_utc'])

    if not latest_sample:
        return 0

    """ We have to do math about the light captor because Parrot doesn't send correct data"""
    return {
        'light': round(latest_sample['light']*14000/3),
        'air_temperature': round(latest_sample['air_temperature_celsius'],1),
        'fertilizer': round(latest_sample['fertilizer_level'],1),
        'automatic_watering': round(latest_sample['water_tank_level_percent']),
        'soil_moisture': round(latest_sample['soil_moisture_percent']),
        'battery': round(latest_sample['battery_percent'])
    }[sensor_type]



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
