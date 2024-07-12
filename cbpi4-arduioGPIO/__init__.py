from telemetrix_aio import telemetrix_aio
import logging
import asyncio
from cbpi.api import *

logger = logging.getLogger(__name__)

# Define Arduino types
ArduinoTypes = {
    "Uno": {
        "digital_pins": list(range(28)),
        "pwm_pins": [3, 5, 6, 9, 10, 11],
        "name": "Uno"
    },
    "Nano": {
        "digital_pins": list(range(28)),
        "pwm_pins": [3, 5, 6, 9, 10, 11],
        "name": "Nano"
    },
    "Mega": {
        "digital_pins": list(range(54)),
        "pwm_pins": [2, 3, 5, 6, 9, 10, 11, 12, 13, 44, 45, 46],
        "name": "Mega"
    }
}

global board

async def TelemetrixInitialize():
    global board
    logger.info("***************** Start Telemetrix  ************************")
    try:
        loop1 = asyncio.get_event_loop()
        board = telemetrix_aio.TelemetrixAIO(autostart=False, loop=loop1)
        await board.start_aio()
        logger.info("Telemetrix initialized successfully")
    except Exception as e:
        logger.error(f"Error. Could not activate Telemetrix: {e}")
        board = None

class ArduinoTelemetrix(CBPiExtension):
    def __init__(self, cbpi):
        self.cbpi = cbpi
        self._task = asyncio.create_task(self.init_actor())

    async def init_actor(self):
        await TelemetrixInitialize()

@parameters([Property.Select(label="GPIO", options=ArduinoTypes['Mega']['digital_pins']), Property.Select(label="Inverted", options=["Yes", "No"], description="No: Active on high; Yes: Active on low")])
class ArduinoGPIOActor(CBPiActor):

    def __init__(self, cbpi, id, props):
        super().__init__(cbpi, id, props)
        self.gpio = int(self.props.get('GPIO', 0))
        self.initial_power = int(self.props.get('Initial Power', 0))
        self.power = self.initial_power
        self.state = False

    async def on_start(self):
        try:
            await board.set_pin_mode_analog_output(self.gpio)
            await board.analog_write(self.gpio, self.power)
            self.state = False
            await self.cbpi.actor.actor_update(self.id, self.power)
            logger.info(f"PWM Actor {self.id} initialized successfully with initial power {self.initial_power}.")
        except Exception as e:
            logger.error(f"Failed to initialize PWM Actor {self.id}: {e}")

    @action("Set Power", parameters=[Property.Number(label="Power", configurable=True, description="Power Setting [0-255]")])
    async def setpower(self, Power=100, **kwargs):
        self.power = min(max(int(Power), 0), 255)
        await self.set_power(self.power)

    async def on(self, power=None):
        if power is not None:
            self.power = power
        else:
            self.power = self.initial_power
        logger.info(f"PWM ACTOR {self.id} ON - GPIO {self.gpio} - Power {self.power}")
        
        try:
            await board.analog_write(self.gpio, self.power)
            self.state = True
            await self.cbpi.actor.actor_update(self.id, self.power)
        except Exception as e:
            logger.error(f"Failed to turn on PWM GPIO {self.gpio}: {e}")

    async def off(self):
        logger.info(f"PWM ACTOR {self.id} OFF - GPIO {self.gpio}")
        
        try:
            await board.analog_write(self.gpio, 0)
            self.state = False
            await self.cbpi.actor.actor_update(self.id, 0)
        except Exception as e:
            logger.error(f"Failed to turn off PWM GPIO {self.gpio}: {e}")

    async def set_power(self, power):
        if self.state:
            try:
                await board.analog_write(self.gpio, int(power))
                await self.cbpi.actor.actor_update(self.id, int(power))
            except Exception as e:
                logger.error(f"Failed to set power for PWM GPIO {self.gpio}: {e}")

    def get_state(self):
        return self.state

def setup(cbpi):
    cbpi.plugin.register("ArduinoGPIOActor", ArduinoGPIOActor)
    cbpi.plugin.register("ArduinoGPIOPWMActor", ArduinoGPIOPWMActor)
    cbpi.plugin.register("ArduinoTelemetrix", ArduinoTelemetrix)
@parameters([
    Property.Select(label="GPIO", options=ArduinoTypes['Mega']['pwm_pins']), 
    Property.Number(label="Initial Power", configurable=True, description="Initial PWM Power (0-255)", default_value=0)
])
class ArduinoGPIOPWMActor(CBPiActor):
    def __init__(self, cbpi, id, props):
        super().__init__(cbpi, id, props)
        self.gpio = int(self.props.get('GPIO', 0))
        self.initial_power = int(self.props.get('Initial Power', 0))
        self.power = self.initial_power
        self.state = False

    async def on_start(self):
        try:
            await board.set_pin_mode_analog_output(self.gpio)
            await board.analog_write(self.gpio, self.power)
            self.state = False
            await self.cbpi.actor.actor_update(self.id, self.power)
            logger.info(f"PWM Actor {self.id} initialized successfully with initial power {self.initial_power}.")
        except Exception as e:
            logger.error(f"Failed to initialize PWM Actor {self.id}: {e}")

    @action("Set Power", parameters=[Property.Number(label="Power", configurable=True, description="Power Setting [0-255]")])
    async def setpower(self, Power=100, **kwargs):
        self.power = min(max(int(Power), 0), 255)
        await self.set_power(self.power)

    async def on(self, power=None):
        if power is not None:
            self.power = power
        else:
            self.power = self.initial_power
        logger.info(f"PWM ACTOR {self.id} ON - GPIO {self.gpio} - Power {self.power}")
        
        try:
            await board.analog_write(self.gpio, self.power)
            self.state = True
            await self.cbpi.actor.actor_update(self.id, self.power)
        except Exception as e:
            logger.error(f"Failed to turn on PWM GPIO {self.gpio}: {e}")

    async def off(self):
        logger.info(f"PWM ACTOR {self.id} OFF - GPIO {self.gpio}")
        
        try:
            await board.analog_write(self.gpio, 0)
            self.state = False
            await self.cbpi.actor.actor_update(self.id, 0)
        except Exception as e:
            logger.error(f"Failed to turn off PWM GPIO {self.gpio}: {e}")

    async def set_power(self, power):
        if self.state:
            try:
                await board.analog_write(self.gpio, int(power))
                await self.cbpi.actor.actor_update(self.id, int(power))
            except Exception as e:
                logger.error(f"Failed to set power for PWM GPIO {self.gpio}: {e}")

    def get_state(self):
        return self.state

def setup(cbpi):
    cbpi.plugin.register("ArduinoGPIOActor", ArduinoGPIOActor)
    cbpi.plugin.register("ArduinoGPIOPWMActor", ArduinoGPIOPWMActor)
    cbpi.plugin.register("ArduinoTelemetrix", ArduinoTelemetrix)