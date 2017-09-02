#!/usr/bin/env python

import datetime
import logging
import argparse
import json
import time

import paho.mqtt.client as mqtt

import config
import pwm
import pid

logging.basicConfig()
logger = logging.getLogger(__name__)
logger.setLevel(logging.DEBUG)

# Settings:

# The period of one on-off cycle when maintaining/monitoring the average
# temperature.
PWM_PERIOD = datetime.timedelta(0, 600)
PWM_MEASUREMENT_PERIOD = PWM_PERIOD

PID_KP = 2.8
PID_KI = 0.3
PID_KD = 1.8

# The width of the 'target zone'; we'll try to adjust within this and
# learn how much heating is required, but outside that we'll either just
# enable or disable heating.
TARGET_ZONE_WIDTH = 0.6

# Time after which a temperature reading is considered too old to use
STALE_THRESHOLD = datetime.timedelta(0, 600)

# Time after which we might re-issue the same command to the boiler
REISSUE_TIMEOUT = datetime.timedelta(0, 120)

BOILER_COMMAND_OFF = 'X'
BOILER_COMMAND_ON = 'O'

class BoilerControl(object):
    def __init__(self, thermostat_id):
        self.thermostat_id = thermostat_id

    def command(self, cmd):
        raise NotImplementedError

class MqttBoilerControl(BoilerControl):
    """Control boiler using MQTT commands."""
    def __init__(self, thermostat_id, mqttc, zone_demand_topic):
        self.mqttc = mqttc
        self.zone_demand_topic = zone_demand_topic
        super(MqttBoilerControl, self).__init__(thermostat_id)

    def command(self, cmd):
        self.mqttc.publish(self.zone_demand_topic, json.dumps({
            'thermostat': self.thermostat_id,
            'command': cmd}))

class BoilerPWM(pwm.PWM):
    def __init__(self, state, dutycycle, pwmperiod):
        self.state = state
        super(BoilerPWM, self).__init__(dutycycle, pwmperiod)

    def on(self):
        self.state.boiler_command(BOILER_COMMAND_ON)

    def off(self):
        self.state.boiler_command(BOILER_COMMAND_OFF)

# Global state:

class State(object):
    def __init__(self, boiler_control):
        self.now = None
        self.lastCommand = None
        self.lastReading = None
        self.state = None

        self.pwmDutyCycle = None
        self.pwmBoilerCycle = None
        self.pwmMeasurementBegin = None

        self.pid = pid.PID(None, PID_KP, PID_KI, PID_KD)

        self.targetTemp = None
        self.boilerControl = boiler_control

    def update_target_temperature(self, target):
        if target != self.targetTemp:
            logger.info("Target temperature changed from %s to %s",
                        str(self.targetTemp), target)
            self.targetTemp = target
            self.pid.reset(target)

    def update_state(self, new_state):
        if self.state != new_state:
            oldname, _, _ = ("None", None, None) if not self.state \
                            else state_fns[self.state]
            name, _, enter = state_fns[new_state]
            logger.info("Transitioning from state %s to %s", oldname, name)
            self.state = new_state

            # If it has an entry function, run it:
            if enter:
                enter(self)

    def boiler_command(self, cmd):
        if self.lastCommand is None or \
           self.now - self.lastCommand.when > REISSUE_TIMEOUT or \
           self.lastCommand.cmd != cmd:
            logger.info("Issuing boiler command %s to %s",
                        cmd, str(self.boilerControl))
            if self.boilerControl:
                self.boilerControl.command(cmd)
            self.lastCommand = TempCommand(self.now, cmd)

    def last_temperature(self):
        return None if self.lastReading is None \
               else self.lastReading.temp

    def target_zone_max(self):
        return self.targetTemp + TARGET_ZONE_WIDTH / 2
    def target_zone_min(self):
        return self.targetTemp - TARGET_ZONE_WIDTH / 2

    def temperature_reading_stale(self):
        return self.targetTemp is None or \
               self.lastReading is None or \
               self.lastReading.when < (self.now - STALE_THRESHOLD)

    def update_duty_cycle(self, dc):
        self.pwmDutyCycle = datetime.timedelta(0, PWM_PERIOD.total_seconds() * dc)
        if not self.pwmBoilerCycle:
            self.pwmBoilerCycle = BoilerPWM(self, self.pwmDutyCycle, PWM_PERIOD)
        else:
            self.pwmBoilerCycle.setDutyCycle(self.pwmDutyCycle)

    def update_temperature(self, temp):
        self.lastReading = TempReading(self.now, temp)
        logger.debug("Temperature update: %s", str(temp))

class TempReading(object):
    def __init__(self, when, temp):
        self.when = when
        self.temp = temp

class TempCommand(object):
    def __init__(self, when, cmd):
        self.when = when
        self.cmd = cmd

# State implementations:

(MODE_OFF, MODE_ON, MODE_PWM, MODE_STALE) = range(4)

def mode_off(state):
    # If we moved below the top of the target zone, set the state
    # accordingly
    if state.last_temperature() < state.target_zone_min():
        state.update_state(MODE_ON)
    elif state.last_temperature() < state.targetTemp:
        state.update_state(MODE_PWM)
    else:
        state.boiler_command(BOILER_COMMAND_OFF)

def mode_on(state):
    # If for some reason (unexpectedly) we ended up above the target zone,
    # switch heating off:
    if state.last_temperature() > state.target_zone_max():
        logger.warn("Temperature got above target zone from MODE_ON")
        state.boiler_command(BOILER_COMMAND_OFF)
        state.update_state(MODE_OFF)
        return

    # If we are within target zone, switch to the PID controller:
    if state.last_temperature() >= (state.targetTemp - TARGET_ZONE_WIDTH / 2):
        logger.info("Temperature in target zone")
        state.boiler_command(BOILER_COMMAND_OFF)
        state.update_state(MODE_PWM)
        return

    # Otherwise, just keep the boiler going:
    state.boiler_command(BOILER_COMMAND_ON)

def mode_pwm_enter(state):
    # Record the temperature target when we enter, so that we know whether
    # to keep state on exit (i.e. if we messed up and temperature left the
    # target zone even though the target didn't change).
    state.pwmBoilerCycle = BoilerPWM(state, datetime.timedelta(0), PWM_PERIOD)
    state.pid.setLastValue(state.last_temperature())

def mode_pwm(state):
    # If we go outside the target zone, switch modes:
    if state.last_temperature() > state.target_zone_max():
        logger.error("Exceeded target zone in PWM mode")
        state.update_state(MODE_OFF)
        return
    if state.last_temperature() < state.target_zone_min():
        logger.error("Dropped below target zone in PWM mode")
        state.update_state(MODE_ON)
        return

    # New measurement cycle?
    if state.pwmMeasurementBegin is None or \
       state.pwmMeasurementBegin + PWM_MEASUREMENT_PERIOD < state.now:
        state.pwmMeasurementBegin = state.now
        # Adjust duty cycle:
        pid_output = state.pid.update(state.last_temperature())
        state.update_duty_cycle(pid_output)

        logger.debug("PID ouutput: %f", pid_output)
        logger.debug("PID internals: prop %f, int %f, diff %f",
                     state.pid.last_prop, state.pid.error_integral,
                     state.pid.last_diff)
        logger.debug("New measurement cycle started")

    state.pwmBoilerCycle.update(state.now)

def mode_stale(state):
    # Ideally we'd cycle the zone periodically to avoid freezing, given we
    # don't have information to do anything better.  For now, just turn the
    # zone off:
    state.boiler_command(BOILER_COMMAND_OFF)

# Mode -> (Mode fn, enter fn)
state_fns = {
    MODE_OFF: ("Off", mode_off, None),
    MODE_ON: ("On", mode_on, None),
    MODE_PWM: ("PWM", mode_pwm, mode_pwm_enter),
    MODE_STALE: ("Stale", mode_stale, None),
    }

def period(state):
    if state.temperature_reading_stale():
        # Don't use stale temperature readings to make decisions:
        state.update_state(MODE_STALE)
    elif state.state is None or state.state == MODE_STALE:
        # If we just a reading after having had stale or no data, pick
        # a starting state from scratch:
        if state.last_temperature() < (state.targetTemp - TARGET_ZONE_WIDTH / 2):
            state.update_state(MODE_ON)
        elif state.last_temperature() > (state.targetTemp + TARGET_ZONE_WIDTH / 2):
            state.update_state(MODE_OFF)
        else:
            state.update_state(MODE_PWM)

    # Now do whatever we're supposed to in this state:
    _, state_fn, _ = state_fns[state.state]
    state_fn(state)

# Temperature reading update:
def on_connect(client, userdata, flags, rc):
    if rc:
        logger.error("Error connecting, rc %d", rc)
        return
    client.subscribe(userdata['tempsensor'])
    client.subscribe(userdata['target_temp'])
    client.publish(userdata['thermostat_status_topic'], json.dumps({
        'thermostat_id': userdata['thermostat_id'],
        'status': 'online'}))

def on_message(client, userdata, msg):
    state = userdata['state']

    def temperature_update():
        data = json.loads(msg.payload)
        if 'temperature' not in data:
            return

        try:
            temp = float(data['temperature'])
        except ValueError:
            return

        now = datetime.datetime.now()
        state.now = now
        state.update_temperature(temp)

        # Print information for debugging/graphing:
        duty_cycle = state.pwmDutyCycle.total_seconds() \
                     if state.pwmDutyCycle else 0
        print now, state.targetTemp, state.lastCommand.cmd, duty_cycle, \
              state.last_temperature(), state.pid.last_prop, \
              state.pid.error_integral, state.pid.last_diff

    def target_update():
        # Payload should be dictionary with key 'target':
        try:
            target = float(json.loads(msg.payload)['target'])
            userdata['state'].update_target_temperature(target)
        except (KeyError, ValueError):
            pass

    if msg.topic == userdata['tempsensor']:
        temperature_update()
    elif msg.topic == userdata['target_temp']:
        target_update()

def maintain_temp(sensor_topic, thermostat_id, dry_run):
    conf = config.load_config()
    mqttc = mqtt.Client()
    if not dry_run:
        boiler_control = MqttBoilerControl(
            thermostat_id, mqttc, conf.get('heating', 'demand_request_topic'))
    else:
        boiler_control = None
    state = State(boiler_control)

    mqttc.user_data_set({
        'state': state,
        'tempsensor': sensor_topic,
        'target_temp': conf.get('heating', 'target_temp_topic'),
        'thermostat_status_topic': conf.get('heating',
                                            'thermostat_status_topic'),
        'thermostat_id': thermostat_id,
        })
    mqttc.on_connect = on_connect
    mqttc.on_message = on_message
    mqttc.username_pw_set(conf.get('mqtt', 'user'),
                          conf.get('mqtt', 'password'))
    mqttc.will_set(
        conf.get('heating', 'thermostat_status_topic'),
        json.dumps({'thermostat_id': thermostat_id, 'status': 'offline'}))
    mqttc.connect(conf.get('mqtt', 'host'), 1883, 60)

    mqttc.loop_start()
    while True:
        time.sleep(1)
        state.now = datetime.datetime.now()
        period(state)

def main():
    parser = argparse.ArgumentParser(description="Maintain target temperature")
    parser.add_argument("-n", action="store_true", dest="dry_run")
    parser.add_argument("sensor_topic")
    parser.add_argument("thermostat_id")
    args = parser.parse_args()

    maintain_temp(args.sensor_topic, int(args.thermostat_id, 0), args.dry_run)

if __name__ == "__main__":
    main()
