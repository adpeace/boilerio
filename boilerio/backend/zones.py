import datetime
from flask_restx import Namespace, Resource, fields, marshal
from flask import current_app, request

from . import model
from .util import get_db, csrf_protection
from .status import zone_status


api = Namespace('Zones', title="Zone management")


a_zone = api.model('Zone', {
    'zone_id': fields.Integer(description="ID of zone"),
    'name': fields.String(),
    'boiler_relay': fields.String(
        description="Identifier of boiler relay for this zone."),
    'sensor_id': fields.Integer(
        description="Identifier of sensor for this zone.."),
    })


@api.route("/")
class ListZones(Resource):
    @api.marshal_list_with(a_zone)
    def get(self):
        db = get_db()
        zones = model.Zone.all_from_db(db)
        return zones


status_override = api.model('Desired zone override', {
    'temperature': fields.Float(),
    'expires_at': fields.DateTime(description='Override deadline as a UTC instant.'),
})
desired_status = api.model('Desired zone status', {
    'target_temperature': fields.Float(description='Current configured target; null without a schedule or override.'),
    'override': fields.Nested(status_override, allow_null=True),
})
reported_status = api.model('Reported zone status', {
    'received_at': fields.DateTime(description='Last report receipt time; not a heartbeat.'),
    'target_temperature': fields.Float(),
    'current_temperature': fields.Float(),
    'current_outside_temperature': fields.Float(),
    'controller_state': fields.String(),
    'duty_cycle': fields.Float(),
    'time_to_target': fields.Integer(description='Estimated seconds to target.'),
    'override_active': fields.Boolean(description='Controller acknowledgement; null for older reports.'),
})
zone_status_model = api.model('Zone status', {
    'zone_id': fields.Integer(),
    'name': fields.String(),
    'sensor_id': fields.Integer(),
    'desired': fields.Nested(desired_status),
    'reported': fields.Nested(reported_status, allow_null=True),
})
status_response = api.model('Zone status response', {
    'as_of': fields.DateTime(description='Server time used to evaluate desired settings.'),
    'schedule_timezone': fields.String(description='IANA timezone for weekly schedule times.'),
    'zones': fields.List(fields.Nested(zone_status_model)),
})


@api.route('/status')
class ZoneStatuses(Resource):
    """Configured targets and the latest controller observations for all zones."""

    @api.marshal_with(status_response)
    @api.response(401, 'Authentication required')
    def get(self):
        return zone_status(get_db(), current_app.extensions['heating_timezone'])


@api.route('/<int:zone_id>/status')
class ZoneStatus(Resource):
    """The same status contract restricted to a single configured zone."""

    @api.response(200, 'Success', status_response)
    @api.response(404, 'Unknown zone')
    def get(self, zone_id):
        result = zone_status(get_db(), current_app.extensions['heating_timezone'], zone_id)
        if result is None:
            return 'Unknown zone', 404
        return marshal(result, status_response)


an_override = api.model("Temperature target override", {
    'zone': fields.Integer(description="Which zone it applies to"),
    'end': fields.DateTime(description="Date/time the override ends"),
    'temp': fields.Float(description="Target temperature during override"),
    })


@api.route("/<int:zone_id>/override")
class Override(Resource):
    """Temperature override for a zone."""
    @api.response(code=200, model=an_override, description="OK")
    @api.response(code=204, description="No overrides active")
    def get(self, zone_id):
        """Get temperature override for zone.

        Returns no override if an override was in place but has expired."""
        # XXX we shouldn't be deciding on the server whether an override is
        # active since it doesn't tell us whether the controller is implementing it
        # or not.  This should move to target/reported state model.
        now = datetime.datetime.now(datetime.timezone.utc)
        db = get_db()
        overrides = model.TargetOverride.from_db(db, [zone_id])
        if not overrides:
            return None, 204

        assert len(overrides) == 1, "Only support one override per zone"
        override = overrides[0]
        if override.end > now:
            return marshal(override, an_override), 200
        return None, 204

    @api.doc(params={
        "temp": {'description': "The override temperature to set.",
                 'type': float, 'required': True, 'in': 'formData'},
        "days": {"type": int, "in": "formData"},
        "hours": {"type": int, "in": "formData"},
        "mins": {"type": int, "in": "formData"},
    })
    @csrf_protection
    def post(self, zone_id):
        """Configure a temperature override.

        Sepcify at least one of hours, mins, secs for duration."""
        try:
            secs = 0
            if 'days' in request.form:
                secs += int(request.form['days']) * 60 * 60 * 24
            if 'hours' in request.form:
                secs += int(request.form['hours']) * 60 * 60
            if 'mins' in request.form:
                secs += int(request.form['mins']) * 60
            if secs <= 0:
                return 'Must specify days, hours, or mins', 400

            duration = datetime.timedelta(0, secs)
            temp = float(request.form['temp'])
        except (ValueError, OverflowError):
            return '', 400
        now = datetime.datetime.now(datetime.timezone.utc)
        try:
            end = now + duration
        except OverflowError:
            return 'Duration is too large', 400

        db = get_db()
        override = model.TargetOverride(end, temp, zone_id)
        override.save(db)
        db.commit()

        return ('', 200)

    @csrf_protection
    def delete(self, zone_id):
        """Clear temperature override."""
        db = get_db()
        model.TargetOverride.clear_from_db(db, zone_id)
        db.commit()
        return '', 200


a_gradient_measurement = api.model('Temperature gradient', {
    'when': fields.DateTime(
        description="Date/time the measurement was taken."),
    'delta': fields.Float(
        description="Difference between inside and "
        "outside temperature at the start of the measurement."),
    'gradient': fields.Float(
        description="The temperature gradient in degrees C per "
        "hour."),
    })
a_gradient_average = api.model('Temperature gradient average', {
    'delta': fields.Float(
        description="Difference between inside and outside temperature"),
    'gradient': fields.Float(
        description="Average temperature gradient with heating on at "
        "temperature difference of delta."),
    'npoints': fields.Integer(
        description="Number of data points contributing to the average "
        "value given."),
    })


@api.route('/<int:zone_id>/gradient_measurements')
class Gradient(Resource):
    @api.expect(a_gradient_measurement)
    @csrf_protection
    def post(self, zone_id):
        try:
            when = datetime.datetime.fromisoformat(api.payload['when'])
            tgm = model.TemperatureGradientMeasurement(
                    zone_id, when, api.payload['delta'],
                    api.payload['gradient'])
        except (ValueError, KeyError, TypeError):
            return 'when must be an ISO timestamp with a UTC offset', 400
        db = get_db()
        tgm.save(db)
        db.commit()


@api.route('/<int:zone_id>/gradients')
class GradientTable(Resource):
    @api.marshal_list_with(a_gradient_average)
    def get(self, zone_id):
        db = get_db()
        r = model.TemperatureGradientMeasurement.get_gradient_table(
                db, zone_id)
        return r


a_controller_state = api.model('Controller reported state', {
    'time_to_target': fields.Integer(
        description="Seconds until target reached."),
    'state': fields.String(description="State of the controller for this zone."),
    'target': fields.Float(
        description="Target the controller is working towards."),
    'current_temp': fields.Float(
        description="Current temperature reported by the controller."),
    'target_overridden': fields.Boolean(
        descripton="Whether the target temperature has been overridden"),
    "current_outside_temp": fields.Float(
        description="Current outside temperature reported by the controller."),
    "dutycycle": fields.Float(description="Dutycycle for boiler"),
    })


@api.route('/<int:zone_id>/reported_state')
@api.param('zone_id', 'Zone ID for the time to target.')
class ReportedState(Resource):
    @api.expect(a_controller_state)
    @csrf_protection
    def post(self, zone_id):
        db = get_db()
        controller_state = model.ControllerState(
                datetime.datetime.now(datetime.timezone.utc),
                zone_id, api.payload['state'], api.payload['target'],
                api.payload['current_temp'], api.payload['time_to_target'],
                api.payload['current_outside_temp'], api.payload['dutycycle'],
                api.payload.get('target_overridden'))
        controller_state.save(db)
        db.commit()

    @api.marshal_with(a_controller_state)
    def get(self, zone_id):
        db = get_db()
        controller_state = model.ControllerState.last_from_db(db, zone_id)
        db.commit()
        return controller_state


@api.route('/<int:zone_id>/schedule')
@api.param('zone_id', 'Zone ID for the schedule.')
class ZoneSchedule(Resource):
    def get(self, zone_id):
        db = get_db()
        schedule = model.FullSchedule.from_db(db, zone_id)
        db.commit()

        entries = []
        for (dow, time, _, temp) in schedule:
            entries.append({
                'day': dow,
                'time': time.strftime('%H:%M'),
                'temp': temp,
            })
        return entries
