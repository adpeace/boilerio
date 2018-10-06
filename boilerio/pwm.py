import datetime
import logging

logging.basicConfig()
logger = logging.getLogger(__name__)
logger.setLevel(logging.DEBUG)

class PWM(object):
    """Performs pulse-width modulation."""
    def __init__(self, dutycycle, period, device):
        """Initialise PWM state.

        dutycycle: a timedelate representing the time duration the device
                   should be on (weird naming...).
        period: the duration of a full cycle (on + off)
        device: an object implementing on and off methods."""
        self.dutycycle = dutycycle
        self.period = period
        self.active = False
        self.periodBegin = None
        self.device = device

    def setDutyCycle(self, dutycycle):
        self.dutycycle = dutycycle

    def update(self, now):
        # Begin new cycle?
        if self.periodBegin is None or \
           self.periodBegin + self.period <= now:
            logger.debug("Beginning PWM new cycle @ %s", str(now))
            self.periodBegin = now
            if self.dutycycle > datetime.timedelta(0, 0):
                self.device.on()
                self.active = True
            return

        # End of 'on' cycle?
        if (self.periodBegin + self.dutycycle) <= now:
            if self.dutycycle <= self.period and self.active:
                logger.debug("End of PWM duty cycle @ %s", str(now))
                self.device.off()
                self.active = False
            return

