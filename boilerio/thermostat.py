import datetime
import logging

from .tempsensor import TempReading
from boilerio import pid, pwm

logging.basicConfig()
logger = logging.getLogger(__name__)
logger.setLevel(logging.DEBUG)

class TemperatureSetting(object):
    def __init__(self, target, zone_width=0.6):
        self._target = target
        self._zone_width = zone_width

    @property
    def target(self):
        return self._target

    @property
    def target_zone_min(self):
        return self._target - self._zone_width / 2

    @property
    def target_zone_max(self):
        return self._target + self._zone_width / 2

class Thermostat(object):
    """Represents a thermostat.

    Manage a boiler given a termpature input."""
    STALE_PERIOD = datetime.timedelta(0, 600)

    # The period of one on-off cycle when maintaining/monitoring the average
    # temperature.
    PWM_PERIOD = datetime.timedelta(0, 600)

    PID_KP = 2.8
    PID_KI = 0.3
    PID_KD = 1.8

    def __init__(self, boiler, sensor, state_change_callback=None):
        """Initialise thermostat object.

        boiler: an object with 'on' and 'off' methods"""
        self._boiler = boiler
        self._pid = pid.PID(None, self.PID_KP, self.PID_KI, self.PID_KD)
        self._pwm_control = pwm.PWM(0, self.PWM_PERIOD, boiler)
        self._state_change_callback = state_change_callback
        self._measurement_begin = None
        self._sensor = sensor
        self._target = None
        self._state = None

    def _notify_state(self, new_state):
        if new_state != self._state:
            logger.debug("%s: State transition %s -> %s", str(self),
                         self._state, new_state)
            self._state = new_state
            if self._state_change_callback is not None:
                self._state_change_callback(self._state)

    def set_state_change_callback(self, state_change_callback):
        self._state_change_callback = state_change_callback

    @property
    def target(self):
        return self._target.target if self._target else None

    @property
    def state(self):
        return self._state

    def set_target_temperature(self, target):
        """Set a target temperature.

        target: a floating-point target temperature value."""
        if (self._target is None or
           (self._target and self._target.target != target)):
            self._target = TemperatureSetting(target)
            self._pid.reset(target)

    def interval_elapsed(self, now):
        """Act on time interval passing.

        now: the current datetime"""
        if (self._sensor.temperature is None or self._target is None or
                self._sensor.temperature.when < (now - self.STALE_PERIOD)):
            # Reading is stale: turn off the boiler:
            self._notify_state('Stale')
            self._boiler.off()
        elif self._sensor.temperature.reading < self._target.target_zone_min:
            # Reading is valid and below target range:
            self._notify_state('On')
            self._boiler.on()
        elif (self._sensor.temperature.reading > self._target.target_zone_min and
              self._sensor.temperature.reading <= self._target.target_zone_max):
            # Reading is valid and within the target range:
            # New measurement cycle?
            self._notify_state('PWM')
            if (self._measurement_begin is None or
                    self._measurement_begin + self.PWM_PERIOD < now):
                self._measurement_begin = now
                # Adjust duty cycle:
                pid_output = self._pid.update(self._sensor.temperature.reading)
                self._pwm_control.setDutyCycle(pid_output)

                logger.debug("PID output: %f", pid_output)
                logger.debug("PID internals: prop %f, int %f, diff %f",
                             self._pid.last_prop, self._pid.error_integral,
                             self._pid.last_diff)
                logger.debug("New measurement cycle started")
            self._pwm_control.update(now)
        elif self._sensor.temperature.reading > self._target.target_zone_max:
            # Reading is valid and above the target range:
            self._notify_state('Off')
            self._boiler.off()
