import json
import datetime
import logging

logging.basicConfig()
logger = logging.getLogger(__name__)
logger.setLevel(logging.DEBUG)


class TempReading(object):
    def __init__(self, when, temp):
        self.when = when
        self.reading = temp

    def __str__(self):
        return "<TempReading: %f deg C at %s>" % (self.reading, self.when)


class EmonTHSensor(object):
    """A temperature sensor from OpenEnergyMonitor."""

    def __init__(self, sensor_id, locator):
        self.temperature = None
        self.sensor_id = sensor_id
        self.locator = locator
        self._callbacks = []

    def register_mqtt_callbacks(self, mqttc):
        logger.debug("Registering callback for %d at %s" %
                     (self.sensor_id, self.locator))
        mqttc.message_callback_add(self.locator, self._temp_callback)

    def add_callback(self, cb):
        self._callbacks.append(cb)

    def _temp_callback(self, client, userdata, msg):
        """Handle MQTT message from emon."""
        try:
            if self.locator != msg.topic:
                return

            data = json.loads(msg.payload)
            temp = float(data['temperature'])
            if self.temperature and temp == self.temperature.reading:
                return

            now = datetime.datetime.now()
            self.temperature = TempReading(now, temp)
        except Exception:
            logger.critical("Exception escaped from MQTT handler for %s",
                            str(self), exc_info=True)

        # Call callbacks:
        logger.debug("Temperature update: %s", str(self.temperature))
        for cb in self._callbacks:
            cb(self)
