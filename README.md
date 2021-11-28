# The BoilerIO Software Thermostat

BoilerIO can control heating in your home.  Code is provided here to connect
with Danfoss RF receivers though other implementations could easily be added,
and to receive temperature updates over MQTT in a format described later in this
README.

This has been tested with the Danfoss RF transciever code in the thermostat.git
repository at https://github.com/adpeace/thermostat.git.

No warranty is provided: please be careful if you are messing with your own
heating system.

For more information, please see https://hackingathome.wordpress.com.

## Installation

More details on installation to be written.  There are several components that
need to be configured:

1.  The web application and database, to provide the online component.
1.  The local scheduler and boiler interface.
1.  The sensor inputs

You can install from the repository to get a specific version, such as the
latest development version not yet published to PyPI, or install via `pip` from
PyPI for a recent tested version by running:

```
pip install boilerio
```

To install from the git repository, first check it out then install using `pip`:

```
$ git clone https://github.com/adpeace/boilerio.git
$ cd boilerio
$ pip3 install .
```

Use `-e` to `pip` to install in development mode (i.e. just link to the
checked-out source instead of installing it).

### Raspberry Pi Quickstart to get MQTT-based on/off control working

You can run these steps on a Raspberry Pi with a fresh SD card that has the Buster version of Raspbian.  You can ssh to the Raspberry Pi, then copy/paste these commands into the terminal.  You'll need a transceiver device such as a JeeLink with the `thermostat` firmware (available at https://github.com/adpeace/thermostat) plugged in to use this.

```
sudo apt install -y python3-pip git
git clone https://github.com/adpeace/boilerio.git
cd boilerio
sudo pip3 install --upgrade pip  # good practise but not mandatory
sudo pip3 install .
sudo mkdir /etc/sensors
sudo bash -c 'cat >/etc/sensors/config' <<EOF
[mqtt]
host = mqtt_hostname
user = mqtt_username
password = mqtt_password

[heating]
info_basetopic = heating/zone/info
demand_request_topic = heating/zone/demand
EOF
```

Now use a text editor such as `nano` to edit `/etc/sensors/config` and replace
the MQTT server details with your own.

Now run `boiler_to_mqtt /dev/ttyUSB0` (replacing `/dev/ttyUSB0` with the location
of the Danfoss transceiver device, e.g. your JeeLink; JeeLink will probably show
up at that device name though if you don't have other USB devices connected).

## Overview

The end-to-end application comes in three parts:

1.  The web app backend.  This is the `schedulerweb` Flask app.  It presents a
    REST API for managing a heating schedule, and is used both by the "device"
    implementation (that translates it into boiler on/off commands and typically
    runs "on-site") and the user interface (which is a web app).  The
    recommended configuration is for this to be proxied through nginx and run
    inside uwsgi.  It uses postgres as a storage backend and assumes a database and role exists called `scheduler`.

2.  The thermostat controller.  This is the `scheduler` Python script.  Ensure
    this daemon is running to control the boiler relay and update the cache of
    the current temperature in the backend web app.

3.  The web-based UI.  This talks to the schedulerweb app and presents a UI
    where the current temperature and schedule can be configured.  It is in a separate repository, `boilerio-ui`.

### The web app backend

To run the scheduler flask application for development, using `flask run`:

```
$ FLASK_APP=boilerio/schedulerweb/app.py BOILERIO_CONFIG=settings.cfg flask run
```

The settings file contains database and other configuration parameters.  An exmaple file is in "example-settings.cfg" but you should copy this and update it to suit your needs.

To run in production, you will need to use a production webserver.  I use uWSGI
behind nginx.  Here is an example uWSGI configuration for `schedulerweb`
(assuming you have the Python package installed) - this can be placed in
`/etc/uwsgi/apps-available` on Ubuntu's version of uwsgi:

```
[uwsgi]
socket = /var/www/boilerio/thermostat.sock
module = boilerio.schedulerweb:app
logto = /var/log/uwsgi/boilerio/thermostat.log
env = BOILERIO_SETTINGS=/etc/sensors/settings.cfg
uid = boilerio
gid = www-data
chmod-socket = 664
```

This assumes you have placed your settings file in `/etc/sensors/settings.cfg`.

### scheduler: The device/controller

The local scheduler component provides the timer and thermostat behaviour: it
gets the target temperature periodically from the web service and controls the
boiler by sending messages to the boiler\_to\_mqtt program.

The scheduler takes no arguments: the configuration will come from the web
service.  In order to actuate a boiler, you will need something listening to
MQTT to interface to the boiler relays: the boiler_to_mqtt script can do this.

## Boiler control software: boiler\_to\_mqtt

The `boiler_to_mqtt` script implements an MQTT-topic based interface on top
of the serial protocol provided in the thermostat.git repository.  In short: it
turns the boiler on and off via MQTT.  The serial interface in thermostat.git is
designed to interact with a Danfoss RF thermostat receiver; if you wanted to use
a different receiver you can substitute a different service.

Ordinarily you'd leave this service running so that other services can turn the
boiler on/off as needed.

This service and others in this repository use a common configuration file.  See
below for more information.

You can send learn packets in a loop with a simple shell loop, if you have the
mosquitto clients installed and are running the `boiler_to_mqtt.py` script:

```
echo -n "Learning mode - program boiler then hit enter... "
while ! read -t 1 ; do
    mosquitto_pub -h <host> -u <username> -P <passwd> -t heating/zone/demand \
                  -m '{"command": "L", "thermostat": 47793}'
done
```

## boilersim

This is a trivial simulator intended to help debug and improve the thermostat.
It follows a really simple heating/cooling model and generates a table as
output.

To run, use a command-line such as:

```
$ boilersim -r 18 19.5 600
```

The `-r` option introduces some random noise into the temperature readings
generated by the simulation when passing them to the controller.

The first positional argument is the starting indoor temperature to simulate.
The second argument is the target temperature.  The third argument is
the simulated runtime in minutes.

This program produces logging output to stderr, and a space-separated output to
stdout.  The output is similar to:

```
...
1.0 0 0 17.9964773317 17.9876417779 0 0 0
...
```

The columns are:

1. The time into the simulation, in minutes
2. The amount of time in that minute that the boiler was on for in the
simulation.
3. The current duty cycle of the boiler in the simulation.
4. The current simulated room temperature
5. The fake temperature reading passed to the controller including any error
introduced by the `-r` option.
6. The current value of the proportional term of the PID controller.
7. The current value of the integral term of the PID controller.
8. The current value of the differential term of the PID controller.

You can use the `plot\_sim.gpi` gnuplot script to plot the output of the
simulation.  E.g.:

```
$ boilersim -r 18 19.5 600  2>log >sim_data
$ gnuplot plot_sim.gpi
```

The gnuplot script assumes the simulation output is saved to a file called
`sim\_data`.

# Config file

Other than `boilersim`, a config file is needed for the programs here.  This is
to help make them usable as daemons.

```
[mqtt]
host = raspi.lan
user = user
password = imnottellingyou

[heating]
# Various MQTT topic names to use.  These can be anything but are specified in
# the config in case you have other software that constrains your choices, and
# ensures they are consistent across apps.

info_basetopic = heating/zone/info
demand_request_topic = heating/zone/demand
thermostat_schedule_change_topic = heating/thermostat_control/update

scheduler_db_host = hub.lan
scheduler_db_name = scheduler
scheduler_db_user = scheduler
scheduler_db_password = imnottellingyou

scheduler_url = https://your_url
scheduler_username = your_user
scheduler_password = imnottellingyou
```
