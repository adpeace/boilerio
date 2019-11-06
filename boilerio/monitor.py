#!/usr/bin/env python

from datetime import timedelta, datetime
import logging
import json
import requests
import requests.exceptions
from requests.auth import HTTPBasicAuth
import paho.mqtt.client as mqtt

from . import config
from . import scheduler
from . import weather

logging.basicConfig()
logger = logging.getLogger(__name__)
logger.setLevel(logging.DEBUG)

class Monitor(object):
    CAPTURE_FIRST, CAPTURE_INTERVAL = list(range(2))

    def __init__(self, warmup_interval_s=600):
        self._boiler_on_time = None
        self._first_temp_recording = None
        self._first_temp_time = None
        self._mode = self.CAPTURE_FIRST
        self._outside_temperature = None
        self._outside_temperature_time = None
        self._warmup_interval = timedelta(seconds=warmup_interval_s)

    def set_outside_temperature(self, value, when):
        self._outside_temperature = value
        self._outside_temperature_time = when

    def temperature_update(self, temp, when):
        """Call to indicate tempreature update.  Returns a record to record or None.

        Returns a temperature gradient in degrees per hour if appropriate,
        otherwise None.  The return value will be pair:
            (delta temp, heating gradient)
        """
        if self._boiler_on_time is None:
            logger.debug("No boiler on time")
            return None

        if self._outside_temperature is None:
            logger.debug("No outside temperature")
            return None

        if (self._mode == self.CAPTURE_FIRST and
            (when - self._boiler_on_time > self._warmup_interval)):
            self._first_temp_recording = temp
            self._first_temp_time = when
            self._mode = self.CAPTURE_INTERVAL
            logger.debug("Captured first")
            return None

        # First temperature value captured: get one after the capture interval
        if (self._mode == self.CAPTURE_INTERVAL and
            (when - self._first_temp_time > timedelta(minutes=10))):
            delta_temp = temp - self._first_temp_recording
            delta_time = when - self._first_temp_time
            delta_time_hours = delta_time.total_seconds() / 3600.0
            self._mode = self.CAPTURE_FIRST
            return (self._first_temp_recording - self._outside_temperature,
                    delta_temp / delta_time_hours)

        logger.debug("Not yet after the capture interval (now: %s, last: %s, boiler on %s, mode %d).",
                     'None' if when is None else when.strftime("%Y-%m-%dT%H:%M"),
                     'None' if self._first_temp_time is None else
                        self._first_temp_time.strftime("%Y-%m-%dT%H:%M"),
                     'None' if self._boiler_on_time is None else
                        self._boiler_on_time.strftime("%Y-%m-%dT%H:%M"),
                     self._mode)
        return None

    def boiler_on(self, when):
        """Signal that the boiler was turned on."""
        if self._boiler_on_time is None:
            self._boiler_on_time = when

    def boiler_off(self, when):
        """Signal that the boiler was turned on."""
        self._boiler_on_time = None

class MqttMonitor(Monitor):
    def __init__(self, mqttc, zone_info_topic, sensor_topic, weather,
            gradient_callback_fn, warmup_interval_s=600,
            weather_update_interval_s=3600):
        """Initialize MqttMonitor.

        gradient_callback_fn is a function that is called when a new
        gradient is found.  It should take two parameter: 'delta' and
        'gradient' which are the delta that the gradient was observed at
        and the inside gradient when heating was on in degrees C per hour.
        """
        self.weather = weather
        self.weather_update_interval = timedelta(seconds=weather_update_interval_s)
        self.gradient_callback_fn = gradient_callback_fn

        # Set up MQTT callbacks:
        mqttc.message_callback_add(sensor_topic, self.mqtt_temperature_update)
        mqttc.message_callback_add(zone_info_topic, self.mqtt_relay_update)

        super(MqttMonitor, self).__init__(warmup_interval_s)

    def mqtt_temperature_update(self, mqttc, userdata, msg):
        logger.debug("%s: %s", msg.topic, msg.payload)
        now = datetime.now()
        data = json.loads(msg.payload)

        # Should we update the outside temperature?
        # XXX using CachingWeather instead...
        if (self._outside_temperature is None or
            now - self._outside_temperature_time < self.weather_update_interval):
            try:
                w = self.weather.get_weather()
                logger.info("Updating weather information: %s", str(w))
                self.set_outside_temperature(w['temperature'], now)
            except:
                logging.error("Unable to get weather.  Skipping update this "
                              "iteration")
        try:
            temp = float(data['temperature'])
        except ValueError as e:
            logging.error("Unable to parse temperature value %s, ignoring", data['temperature'])
            return

        r = self.temperature_update(temp, now)
        if r is not None:
            logger.info("%s: Temperature gradient result: %s", msg.topic, str(r))
            self.gradient_callback_fn(now, r[0], r[1])

    def mqtt_relay_update(self, mqttc, userdata, msg):
        logger.debug("%s: %s", msg.topic, msg.payload)
        now = datetime.now()
        data = json.loads(msg.payload)
        if data['cmd'] == 'OFF':
            self.boiler_off(now)
        elif data['cmd'] == 'ON':
            self.boiler_on(now)

def main():
    conf = config.load_config()

    # Get zone information:
    # If the 'heating' section of the config has a 'scheduler_username' and
    # 'scheduler_password' entry, we use these with HTTP basic auth.
    if conf.has_option('heating', 'scheduler_username') and \
       conf.has_option('heating', 'scheduler_password'):
        logger.info("Using HTTP basic authentication")
        auth = HTTPBasicAuth(conf.get('heating', 'scheduler_username'),
                             conf.get('heating', 'scheduler_password'))
    else:
        logger.info("Not using HTTP authentication")
        auth = None
    scheduler_url = conf.get('heating', 'scheduler_url')
    zones = scheduler.load_zone_info(scheduler_url, auth)

    # Connect to MQTT:
    def mqtt_on_connect(client, userdata, flags, rc):
        if rc:
            logger.error("Error connecting to MQTT: rc %d", rc)
            return
        client.subscribe(conf.get('heating', 'info_basetopic') + '/#')
        for zone in zones:
            client.subscribe(zone.sensor)
    mqttc = mqtt.Client()
    mqttc.username_pw_set(conf.get('mqtt', 'user'),
                          conf.get('mqtt', 'password'))
    mqttc.on_connect = mqtt_on_connect
    mqttc.connect(conf.get('mqtt', 'host'), 1883, 60)

    def post_gradient_fn(zone_id):
        def post_gradient(when, delta, gradient):
            data = {'when': when.isoformat(), 'delta': delta,
                    'gradient': gradient}
            r = requests.post(scheduler_url +
                    '/zones/%d/gradient_measurements' % zone_id,
                    auth=auth, json=data)
            logger.info("Posted gradient %s for zone %d, status code %d",
                    str(data), zone_id, r.status_code)
        return post_gradient

    monitors = [
        MqttMonitor(
            mqttc, conf.get('heating', 'info_basetopic') + '/0x' +
            format(int(zone.boiler_relay, 0), 'X'), zone.sensor,
            weather.Weather(conf.get('weather', 'apikey'),
                            conf.get('weather', 'location')),
            post_gradient_fn(zone.zone_id))
        for zone in zones
    ]

    mqttc.loop_forever()

if __name__ == "__main__":
    main()
