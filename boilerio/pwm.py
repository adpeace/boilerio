import datetime
import logging

logging.basicConfig()
logger = logging.getLogger(__name__)
logger.setLevel(logging.DEBUG)

class PWM(object):
    def __init__(self, dutycycle, period):
        self.dutycycle = dutycycle
        self.period = period
        self.active = False
        self.periodBegin = None

    def setDutyCycle(self, dutycycle):
        self.dutycycle = dutycycle

    def update(self, now):
        # Begin new cycle?
        if self.periodBegin is None or \
           self.periodBegin + self.period <= now:
            logger.debug("Beginning PWM new cycle @ %s", str(now))
            self.periodBegin = now
            if self.dutycycle > datetime.timedelta(0, 0):
                self.on()
                self.active = True
            return

        # End of 'on' cycle?
        if (self.periodBegin + self.dutycycle) <= now:
            if self.dutycycle <= self.period and self.active:
                logger.debug("End of PWM duty cycle @ %s", str(now))
                self.off()
                self.active = False
            return

    def on(self):
        raise NotImplementedError
    def off(self):
        raise NotImplementedError


