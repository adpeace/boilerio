#!/usr/bin/env python

"""Operate heating schedule."""

import sys
import os
import json
import datetime
from datetime import timedelta
import threading
import logging

import paho.mqtt.client as mqtt
import requests
import requests.exceptions
from requests.auth import HTTPBasicAuth

from . import model
from . import config
from . import thermostat
from . import tempsensor
from . import update_sensor
from . import weather

logging.basicConfig()
logger = logging.getLogger(__name__)
logger.setLevel(logging.DEBUG)

strptime = datetime.datetime.strptime
strftime = datetime.datetime.strftime

class MqttBoiler(object):
    """Control boiler using MQTT commands."""
    # Time after which we might re-issue the same command to the boiler
    REISSUE_TIMEOUT = timedelta(0, 120)

    def __init__(self, thermostat_id, mqttc, zone_demand_topic):
        self.mqttc = mqttc
        self.zone_demand_topic = zone_demand_topic
        self.last_cmd = None
        self.last_cmd_time = None
        self.thermostat_id = thermostat_id

    def _command(self, cmd):
        now = datetime.datetime.now()
        if cmd != self.last_cmd or \
           self.last_cmd_time < now - self.REISSUE_TIMEOUT:
            logger.debug("Issuing boiler command %s for relay %s", cmd, self.thermostat_id)
            self.mqttc.publish(self.zone_demand_topic, json.dumps({
                'thermostat': self.thermostat_id,
                'command': cmd}))
            self.last_cmd = cmd
            self.last_cmd_time = now

    def on(self):
        self._command('O')

    def off(self):
        self._command('X')

class ZoneInfoUnavailable(Exception):
    pass

class SchedulerTemperaturePolicy(object):
    ENTRY_TARGET_OVERRIDE = -2

    def __init__(self, schedule, tgt_override):
        """Initialise policy object from FullSchedule and override.

        Note that FullSchedule is basically a wrapper around a list but
        requires that the entries are sorted by day then time then zone.
        """
        self.schedule = schedule
        self.target_override = tgt_override

    @classmethod
    def from_json(cls, j):
        data = json.loads(j)

        entries = []
        for day in sorted(data['schedule']):
            for item in data['schedule'][day]:
                for zone in item['zones']:
                    entries.append((
                        int(day),
                        strptime(item['when'], "%H:%M").time(),
                        zone['zone'],
                        zone['temp']
                        ))
        schedule = model.FullSchedule(entries)
        tgt_override = data['target_override']
        tgt_override = [
            model.TargetOverride(strptime(t['until'], "%Y-%m-%dT%H:%M"),
                                 t['temp'], t['zone'])
            for t in tgt_override
            ]
        return cls(schedule, tgt_override)

    def get_day(self, day, zone):
        """Determine the schedule for today covering the full 24h.

        Uses the overall schedule and any schedule overrides (but not
        target tmperature overrides) in place.

        Returns a list of the form:
            [ (starttime, zone, temperature) ]
        """
        sched_for_zone = [e for e in self.schedule.entries
                          if e[2] == zone]
        if not sched_for_zone:
            return []

        entries = []

        # Populate with the day's entries.  Add an entry from the start
        # of the day based on entry prior to that day:
        candidate_beginning = None
        for sday, starttime, entry_zone, temp in sched_for_zone:
            if entry_zone != zone:
                continue
            if sday == day:
                entries.append((starttime, zone, temp))
            elif sday < day:
                candidate_beginning = temp
        if candidate_beginning is None:
            # Wasn't an earlier entry, use the last one in the schedule:
            _, _, _, temp = sched_for_zone[-1]
            candidate_beginning = temp
        # Check whether we need to fill in the start:
        if not entries or entries[0][0] != datetime.time(0, 0):
            entries.insert(0, (datetime.time(0, 0), zone, candidate_beginning))

        return entries

    def target_overridden(self, now, zone):
        if self.target_override is not None:
            return any(t.zone == zone and t.end > now
                       for t in self.target_override)
        return False

    def target(self, now, zone):
        """Determine temperature target at datetime now."""
        # First check if we are still within an override:
        if self.target_override is not None:
            for override in self.target_override:
                if override.zone == zone and override.end > now:
                    return override.temp

        day_schedule = self.get_day(now.weekday(), zone)
        now_time = now.time()

        # Iterate over the schedule finding the last entry with a lower time
        # than the requested time.  If we don't find one, we need the last
        # entry from the day before.
        target = None
        for sched_time, _, sched_target in day_schedule:
            if sched_time <= now_time:
                target = sched_target
            else:
                break
        return target

def mqtt_on_connect(client, userdata, flags, rc):
    if rc:
        logger.error("Error connecting, rc %d", rc)
        return
    for sensor in userdata['sensors'].values():
        client.subscribe(sensor.locator)
    client.subscribe(userdata['thermostat_schedule_change_topic'])

def mqtt_on_message(client, userdata, msg):
    if msg.topic == userdata['thermostat_schedule_change_topic']:
        userdata['timer_event'].set()

class ZoneController(object):
    """Connect a schedule, thermostat, and temperature sensor."""
    def __init__(self, zone, boiler, sensor, thermostat_obj, scheduler_url,
                 auth, weather,
                 gradient_table_update_frequency=timedelta(hours=1)):
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
                }
        self.do_update_state = True
        self._sensor.add_callback(self.temperature_change)
        self.gradient_table = []
        self.last_gradient_table_update = None
        self.gradient_table_update_frequency = gradient_table_update_frequency
        self.weather = weather

    def thermostat_state_callback(self, new_state):
        self.reported_state['state'] = new_state
        self.do_update_state = True

    def temperature_change(self, sensor):
        # Temperature changed: record in our state.
        self.reported_state['current_temp'] = sensor.temperature.reading
        self.do_update_state = True

    def get_time_to_target(self):
        """Estimate time to reach temperature target.

        Returns a timedelta object."""
        # This algorithm overestimates the time taken because it uses the
        # gradient at the start of heating, whereas it should be using an
        # integral over time.

        # If we're not heating, just return nothing:
        if (self.thermostat.state != 'On' or
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
        self.reported_state['target'] = self.thermostat.target
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
        if self.thermostat.target != target:
            logger.info("Updating target temperature (%s -> %s) for zone %d",
                        str(self.thermostat.target), str(target), self.zone.zone_id)
            self.thermostat.set_target_temperature(target)
            self.do_update_state = True

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

        # Update state:
        if self.do_update_state:
            self.report_updated_state()

def get_url_with_fallback(fallback, url, auth):
    """Gets a URL and updates fallback file.

    Uses fallback file if get request fails.  Returns None if no sources
    are available."""

    # First try to get from web service:
    result = None

    r = requests.get(url, auth=auth)
    if r.status_code == 200:
        try:
            with open(fallback, 'w') as f:
                f.write(r.text)
        except:
            logger.warn("Unable to write backup zone file.")
        result = r.text
    else:
        # That failed, try to get from last backup:
        logger.error("Couldn't retrieve %s from web servive, "
                     "attempting fallback.", url)
        if os.path.exists(fallback):
            try:
                with open(fallback, 'r') as f:
                    result = f.read()
            except:
                logger.error("Couldn't retrive zones from backup.")

    return result

def load_zone_info(scheduler_url, auth):
    """Load zone information from service. """
    BOILERIO_ZONE_BACKUP_FILE = '/var/lib/boilerio/zones'

    zones = json.loads(get_url_with_fallback(BOILERIO_ZONE_BACKUP_FILE,
                                             scheduler_url + '/zones', auth))
    if zones is None:
        raise ZoneInfoUnavailable()

    return [model.Zone(z['zone_id'], z['name'], z['boiler_relay'], z['sensor_id'])
            for z in zones]

def construct_sensors(scheduler_url, auth):
    """Construct sensors from service.

    Return a diction of sensor_id -> EmonTHSensor object"""
    SENSOR_BACKUP_FILE = '/var/lib/boilerio/sensors'

    sensors = json.loads(get_url_with_fallback(SENSOR_BACKUP_FILE,
                                               scheduler_url + '/sensor', auth))
    if sensors is None:
        raise ZoneInfoUnavailable()

    return {
        s['sensor_id']: tempsensor.EmonTHSensor(s['sensor_id'], s['locator'])
        for s in sensors
    }


class AllZoneController(object):
    """Controller for multiple zones.

    Interfaces between the web API and a set of local zone controllers."""

    SCHEDULER_UPDATE_INTERVAL = timedelta(seconds=60)

    def __init__(self, scheduler_url, auth, zone_controllers):
        self.scheduler = None
        self.last_scheduler_update = None

        self.scheduler_url = scheduler_url
        self.auth = auth
        self.zone_controllers = zone_controllers

    def iteration(self, now):
        # Update schedule:
        if self.last_scheduler_update:
            next_scheduler_update = self.last_scheduler_update + self.SCHEDULER_UPDATE_INTERVAL
        if self.scheduler is None or next_scheduler_update < now:
            try:
                r = requests.get(self.scheduler_url + "/schedule",
                                 auth=self.auth, timeout=10)
            except requests.exceptions.RequestException as e:
                logger.error("Failed interval (%s)", str(e))
            else:
                if r.status_code != 200:
                    logger.error("Couldn't get schedule (%d)",
                                 r.status_code)
                else:
                    self.last_scheduler_update = now
                    self.scheduler = SchedulerTemperaturePolicy.from_json(r.text)

        # Update thermostats:
        if self.scheduler:
            for controller in self.zone_controllers:
                controller.iteration(self.scheduler, now)

def main():
    conf = config.load_config()

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

    if len(sys.argv) == 2:
        scheduler_url = sys.argv[1]
    else:
        scheduler_url = conf.get('heating', 'scheduler_url')

    sensors = construct_sensors(scheduler_url, auth)
    zones = load_zone_info(scheduler_url, auth)

    period_event = threading.Event()
    mqttc = mqtt.Client(userdata={
        'conf': conf,
        'thermostat_schedule_change_topic':
            conf.get('heating', 'thermostat_schedule_change_topic'),
        'timer_event': period_event,
        'scheduler_url': scheduler_url,
        'auth': auth,
        'sensors': sensors,
        })
    mqttc.username_pw_set(conf.get('mqtt', 'user'),
                          conf.get('mqtt', 'password'))
    mqttc.on_connect = mqtt_on_connect
    mqttc.on_message = mqtt_on_message
    mqttc.connect(conf.get('mqtt', 'host'), 1883, 60)

    sensor_updater = update_sensor.TempSensorUpdater(scheduler_url, auth)

    zone_controllers = []
    weather_obj = weather.CachingWeather(conf.get('weather', 'apikey'),
            conf.get('weather', 'location'))

    for sensor in sensors.values():
        sensor.register_mqtt_callbacks(mqttc)
        sensor_updater.add_sensor(sensor)

    for zone in zones:
        zone_boiler = MqttBoiler(zone.boiler_relay, mqttc,
                                 conf.get('heating', 'demand_request_topic'))
        zone_sensor = sensors[zone.sensor_id]
        zone_thermostat = thermostat.Thermostat(zone_boiler, zone_sensor)
        zone_controller = ZoneController(zone, zone_boiler, zone_sensor,
                                         zone_thermostat,
                                         scheduler_url, auth, weather_obj)
        zone_controllers.append(zone_controller)

    mqttc.loop_start()

    # Update thermostats every second and schedule every 60s:
    controller = AllZoneController(scheduler_url, auth, zone_controllers)
    while True:
        controller.iteration(datetime.datetime.now())
        period_event.wait(timeout=1)
        period_event.clear()

    mqttc.loop_stop()

if __name__ == "__main__":
    main()
