from homeassistant.helpers.entity import Entity
from homeassistant.const import TEMP_CELSIUS
from homeassistant.components.sensor import PLATFORM_SCHEMA
import voluptuous as vol
import homeassistant.helpers.config_validation as cv

import requests
from pprint import pformat  # here only for aesthetic


PLATFORM_SCHEMA = PLATFORM_SCHEMA.extend({
    vol.Required('username'): cv.string,
    vol.Required('password'): cv.string,
    vol.Required('clientid'): cv.string,
    vol.Required('clientsecret'): cv.string
})

def setup_platform(hass, config, add_devices, discovery_info=None):

    # First we set our credentials
    username = config.get('username')
    password = config.get('password')

    # From the developer portal
    client_id = config.get('clientid')
    client_secret = config.get('clientsecret')


    req = requests.get('https://api-flower-power-pot.parrot.com/user/v1/authenticate',
                       data={'grant_type': 'password',
                             'username': username,
                             'password': password,
                             'client_id': client_id,
                             'client_secret': client_secret,
                            })
    response = req.json()
    print('Server response: \n {0}'.format(pformat(response)))

    # Get authorization token from response
    access_token = response['access_token']
    auth_header = {'Authorization': 'Bearer {token}'.format(token=access_token)}

    # From now on, we won't need initial credentials: access_token and auth_header will be enough.

    # Set your own authentication token
    req = requests.get('https://api-flower-power-pot.parrot.com/user/v4/profile',
                        headers=auth_header)

    response = req.json()
    print('Server response: \n {0}'.format(pformat(response)))

    # Set your own authentication token
    req = requests.get('https://api-flower-power-pot.parrot.com/garden/v1/status',
                       headers=auth_header)

    response = req.json()
    print('Server response: \n {0}'.format(pformat(response)))

    locations = response['locations']
    for location in locations:
        print('location: \n {0}'.format(pformat(location)))
        light = location['light']['gauge_values']['current_value']
        air_temperature = location['air_temperature']['gauge_values']['current_value']
        fertilizer = location['fertilizer']['gauge_values']['current_value']
        watering = location['watering']['automatic_watering']['gauge_values']['current_value']
        soil_moisture = location['watering']['soil_moisture']['gauge_values']['current_value']

        add_devices([FlowerPowerTemperatureSensor(air_temperature), FlowerPowerHumiditySensor(soil_moisture)])


class FlowerPowerTemperatureSensor(Entity):
    """Representation of a Sensor."""

    def __init__(self, temperature):
        """Initialize the sensor."""
        self._state = temperature

    @property
    def name(self):
        """Return the name of the sensor."""
        return 'Flower power temperature sensor'

    @property
    def state(self):
        """Return the state of the sensor."""
        return self._state

    @property
    def unit_of_measurement(self):
        """Return the unit of measurement."""
        return TEMP_CELSIUS

    def update(self):
        """Fetch new state data for the sensor.

        This is the only method that should fetch new data for Home Assistant.
        """
        self._state = temperature

class FlowerPowerHumiditySensor(Entity):
    """Representation of a Sensor."""

    def __init__(self, soil_moisture):
        """Initialize the sensor."""
        self._state = soil_moisture

    @property
    def name(self):
        """Return the name of the sensor."""
        return 'Flower power humidity sensor'

    @property
    def state(self):
        """Return the state of the sensor."""
        return self._state

    @property
    def unit_of_measurement(self):
        """Return the unit of measurement."""
        return '%'

    def update(self):
        """Fetch new state data for the sensor.

        This is the only method that should fetch new data for Home Assistant.
        """
        self._state = soil_moisture
