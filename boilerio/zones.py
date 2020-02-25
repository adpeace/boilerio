from datetime import timedelta
import logging
import requests

logging.basicConfig()
logger = logging.getLogger(__name__)
logger.setLevel(logging.DEBUG)


class ZoneController(object):
    """Connect a schedule, thermostat, and temperature sensor."""

    def __init__(self, zone, boiler, sensor, thermostat_obj, scheduler_url,
                 auth, weather,
                 gradient_table_update_frequency=timedelta(hours=1)):
        """Initialize a zone controller.

        Note that the weather is updated on each iteration so the weather
        object needs to do caching to avoid frequent API calls."""
        self.zone = zone
        self.boiler = boiler
        self.thermostat = thermostat_obj
        self.thermostat.set_state_change_callback(self.thermostat_state_callback)
        self._sensor = sensor
        self.scheduler_url = scheduler_url
        self.scheduler_auth = auth

        self.reported_state = {
                'time_to_target': None,
                'state': 'Unknown',
                'target': None,
                'current_temp': None,
                'current_outside_temp': None,
                'dutycycle': None,
                'target_overridden': None,
                }
        self.do_update_state = True
        self._sensor.add_callback(self.temperature_change)
        self.gradient_table = []
        self.last_gradient_table_update = None
        self.gradient_table_update_frequency = gradient_table_update_frequency
        self.weather = weather

    def thermostat_state_callback(self, new_state, dutycycle):
        self._update_state(state=new_state, dutycycle=dutycycle)

    def temperature_change(self, sensor):
        self._update_state(current_temp=sensor.temperature.reading)

    def _update_state(self, **kwargs):
        """Updates state with arguments passed."""
        new_state = self.reported_state.copy()
        new_state.update(**kwargs)
        if new_state != self.reported_state:
            self.reported_state = new_state
            self.do_update_state = True
            logger.debug("State change: %s", str(kwargs))

    def get_time_to_target(self):
        """Estimate time to reach temperature target.

        Returns a timedelta object."""
        # This algorithm overestimates the time taken because it uses the
        # gradient at the start of heating, whereas it should be using an
        # integral over time.

        # If we're not heating, just return nothing:
        if (not self.thermostat.is_heating or
            self._sensor.temperature is None or
            self.thermostat.target < self._sensor.temperature.reading):
            return None
        else:
            outside = self.weather.get_weather()
            delta_t = self._sensor.temperature.reading - outside['temperature']

            # Find a gradient where the delta between inside and out was
            # closest to the current temperature:
            match = None
            for gradient in self.gradient_table:
                if match is None:
                    match = gradient
                elif (abs(gradient['delta'] - delta_t)
                        < abs(match['delta'] - delta_t)):
                    match = gradient

            # Now use it to estimate heating time:
            if match is None:
                return None
            amount_to_heat = self.thermostat.target - self._sensor.temperature.reading
            return timedelta(hours=(amount_to_heat / match['gradient']))

    def report_updated_state(self):
        url = self.scheduler_url + '/zones/%d/reported_state' % self.zone.zone_id
        ttt = self.get_time_to_target()
        self.reported_state['time_to_target'] = ttt.total_seconds() if ttt else None
        r = requests.post(url, auth=self.scheduler_auth,
            timeout=10, json=self.reported_state)
        if r.status_code == 200:
            logger.info("Reported new state for zone %d: %s",
                    self.zone.zone_id, str(self.reported_state))
            self.do_update_state = False
        else:
            logger.error("Couldn't update state (zone %d, url %s, data %s)",
                    self.zone.zone_id, url, str(self.reported_state))

    def iteration(self, scheduler, now):
        """Update the zone.  Should be called once per second."""
        # Update target temperature by polling scheduler
        target = scheduler.target(now, self.zone.zone_id)
        self._update_state(
            target_overridden=scheduler.target_overridden(now,
                                                          self.zone.zone_id))
        if self.thermostat.target != target:
            logger.info("Updating target temperature (%s -> %s) for zone %d",
                        str(self.thermostat.target), str(target), self.zone.zone_id)
            self.thermostat.set_target_temperature(target)
            self._update_state(target=target)

        # Update gradient table:
        if (self.last_gradient_table_update is None or
                self.last_gradient_table_update + self.gradient_table_update_frequency < now):
            r = requests.get(
                    self.scheduler_url + '/zones/%d/gradients' % self.zone.zone_id,
                    timeout=10, auth=self.scheduler_auth)
            if r.status_code == 200:
                self.gradient_table = r.json()
                self.last_gradient_table_update = now
            else:
                logger.error("Couldn't update gradients table for zone %d (status %d)",
                        self.zone.zone_id, r.status_code)

        # Update thermostat:
        self.thermostat.interval_elapsed(now)

        # Update weather:
        current_weather = self.weather.get_weather()
        self._update_state(current_outside_temp=current_weather['temperature'])

        # Report updated state if necessary:
        if self.do_update_state:
            self.report_updated_state()
