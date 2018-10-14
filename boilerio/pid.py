import logging

logging.basicConfig()
logger = logging.getLogger(__name__)
logger.setLevel(logging.DEBUG)

class PID(object):
    def __init__(self, setpoint, Kp, Ki, Kd):
        self.Kp = Kp
        self.Ki = Ki
        self.Kd = Kd
        self.last_prop = 0
        self.last_pv = None
        self.min_output = 0.15
        self.reset(setpoint)

    def setLastValue(self, val):
        self.last_pv = val

    def reset(self, setpoint):
        self.setpoint = setpoint
        self.last_diff = 0
        self.error_integral = 0

    def update(self, pv):
        if self.setpoint is None:
            return 0
        if self.last_pv is None:
            self.last_pv = pv

        error = self.setpoint - pv

        # Constrain total error to avoid windup problems
        self.error_integral += self.Ki * error
        self.error_integral = max(min(self.error_integral, 1), -1)
        diff = pv - self.last_pv

        self.last_diff = self.Kd * diff
        self.last_prop = self.Kp * error
        self.last_pv = pv

        out = self.Kp * error + self.error_integral - self.Kd * diff
        if out < self.min_output:
            rv = 0
        else:
            rv = max(min(out, 1), self.min_output)
        logger.debug("Unconstrained pid return value %f -> %f", out, rv)

        return rv
