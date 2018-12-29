#!/usr/bin/env python

"""Operate heating schedule."""

import sys
import os
import json
import datetime
import threading
import logging
import paho.mqtt.client as mqtt
import requests
import requests.exceptions
from requests.auth import HTTPBasicAuth

import model
import config
import thermostat

logging.basicConfig()
logger = logging.getLogger(__name__)
logger.setLevel(logging.DEBUG)

strptime = datetime.datetime.strptime
strftime = datetime.datetime.strftime

class MqttBoiler(object):
    """Control boiler using MQTT commands."""
    # Time after which we might re-issue the same command to the boiler
    REISSUE_TIMEOUT = datetime.timedelta(0, 120)

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
    for zone in userdata['zones']:
        client.subscribe(zone.sensor)
    client.subscribe(userdata['thermostat_schedule_change_topic'])

def mqtt_on_message(client, userdata, msg):
    if msg.topic == userdata['thermostat_schedule_change_topic']:
        userdata['timer_event'].set()

class ZoneController(object):
    """Connect a schedule, thermostat, and temperature sensor."""

    def __init__(self, mqttc, zone, boiler, thermostat, scheduler_url,
                 auth):
        self.zone = zone
        self.boiler = boiler
        self.thermostat = thermostat
        self.scheduler_url = scheduler_url
        self.scheduler_auth = auth

        mqttc.message_callback_add(zone.sensor, self.temp_callback)

    def temp_callback(self, client, userdata, msg):
        if self.zone.sensor != msg.topic:
            return
        # This should probably be in its own class: update the cached
        # temperature value on the server:
        try:
            data = json.loads(msg.payload)
            temp = float(data['temperature'])

            now = datetime.datetime.now()
            temp_reading = thermostat.TempReading(now, temp)
            r = requests.post(
                self.scheduler_url + '/temperature',
                auth=self.scheduler_auth,
                timeout=10, data={
                    'when': strftime(now, "%Y-%m-%dT%H:%M:%S"),
                    'temp': temp,
                    'zone': self.zone.zone_id
                })
            logger.info("Cached temperature update for zone %d: %.2f, result %d",
                        self.zone.zone_id, temp, r.status_code)
        except (requests.exceptions.RequestException, ValueError) as e:
            logger.info("Error updating cached temperature (%s)",
                        str(e))

        # Update the thermostat:
        self.thermostat.update_temperature(temp_reading)

    def iteration(self, scheduler, now):
        """Update the zone.  Should be called once per second."""
        # Update target temperature by polling scheduler
        target = scheduler.target(now, self.zone.zone_id)
        if self.thermostat.target != target:
            logger.info("Updating target temperature (%s -> %s) for zone %d",
                        str(self.thermostat.target), str(target), self.zone.zone_id)
            self.thermostat.set_target_temperature(target)

        # Update thermostat:
        self.thermostat.interval_elapsed(now)

def load_zone_info(scheduler_url, auth):
    """Load zone information from service.

    Try to get zone information.  Cache it to disk under /var/lib/boilerio
    in case we can't get it next time.  Get it from the cached location if
    the HTTP request fails and it is present, otherwise fail (since we don't
    know what zones are present).
    """
    BOILERIO_ZONE_BACKUP_FILE = '/var/lib/boilerio/zones'

    zones = None

    # First try to get from web service:
    r = requests.get(scheduler_url + '/zones', auth=auth)
    if r.status_code == 200:
        try:
            with open(BOILERIO_ZONE_BACKUP_FILE, 'w') as f:
                f.write(r.text)
        except:
            logger.warn("Unable to write backup zone file.")
        zones = json.loads(r.text)
    else:
        # That failed, try to get from last backup:
        logger.error("Couldn't retrieve zone information from web servive.")
        if os.path.exists(BOILERIO_ZONE_BACKUP_FILE):
            try:
                with open(BOILERIO_ZONE_BACKUP_FILE, 'r') as f:
                    zones = json.loads(f.read())
            except:
                logger.error("Couldn't retrive zones from backup.")

    if zones is not None:
        return [model.Zone(z['zone_id'], z['name'], z['boiler_relay'], z['sensor'])
                for z in zones]
    raise ZoneInfoUnavailable()

class AllZoneController(object):
    """Controller for multiple zones.

    Interfaces between the web API and a set of local zone controllers."""

    SCHEDULER_UPDATE_INTERVAL = datetime.timedelta(seconds=60)

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

    zones = load_zone_info(scheduler_url, auth)

    period_event = threading.Event()
    mqttc = mqtt.Client(userdata={
        'conf': conf,
        'thermostat_schedule_change_topic':
            conf.get('heating', 'thermostat_schedule_change_topic'),
        'timer_event': period_event,
        'scheduler_url': scheduler_url,
        'auth': auth,
        'zones': zones,
        })
    mqttc.username_pw_set(conf.get('mqtt', 'user'),
                          conf.get('mqtt', 'password'))
    mqttc.on_connect = mqtt_on_connect
    mqttc.on_message = mqtt_on_message
    mqttc.connect(conf.get('mqtt', 'host'), 1883, 60)

    zone_controllers = []
    for zone in zones:
        zone_boiler = MqttBoiler(zone.boiler_relay, mqttc,
                                 conf.get('heating', 'demand_request_topic'))
        zone_thermostat = thermostat.Thermostat(zone_boiler)
        zone_controller = ZoneController(mqttc, zone, zone_boiler, zone_thermostat,
                                         scheduler_url, auth)
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
