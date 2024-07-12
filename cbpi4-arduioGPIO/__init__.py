import asyncio
import logging
from typing import Dict, List, Optional
from cbpi.api import CBPiActor, CBPiExtension, Property, action, parameters
from telemetrix_aio import telemetrix_aio

logger = logging.getLogger(__name__)

# Define Arduino types
ArduinoTypes: Dict[str, Dict[str, List[int] | str]] = {
    "Uno": {
        "digital_pins": list(range(14)),
        "pwm_pins": [3, 5, 6, 9, 10, 11],
        "name": "Uno"
    },
    "Nano": {
        "digital_pins": list(range(14)),
        "pwm_pins": [3, 5, 6, 9, 10, 11],
        "name": "Nano"
    },
    "Mega": {
        "digital_pins": list(range(54)),
        "pwm_pins": [2, 3, 4, 5, 6, 7, 8, 9, 10, 11, 12, 13],
        "name": "Mega"
    }
}

board: Optional[telemetrix_aio.TelemetrixAIO] = None

async def TelemetrixInitialize():
    global board
    logger.info("***************** Start Telemetrix  ************************")
    try:
        loop = asyncio.get_event_loop()
        board = telemetrix_aio.TelemetrixAIO(autostart=False, loop=loop)
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



@parameters([
    Property.Select(label="GPIO", options=ArduinoTypes['Mega']['pwm_pins']), 
    Property.Number(label="Initial Power", configurable=True, description="Initial PWM Power (0-255)", default_value=0)
])
class ArduinoGPIOPWMActor(CBPiActor):
    @action("Set Power", parameters=[Property.Number(label="Power", configurable=True, description="Power Setting [0-255]")])
    async def setpower(self, Power=100, **kwargs):
        self.power = min(max(int(Power), 0), 255)
        await self.set_power(self.power)

    async def on_start(self):
        self.gpio = int(self.props['GPIO'])
        self.initial_power = int(self.props['Initial Power'])
        
        try:
            await board.set_pin_mode_analog_output(self.gpio)
            self.power = self.initial_power
            await board.analog_write(self.gpio, self.power)
            self.state = False
            await self.cbpi.actor.actor_update(self.id, self.power)
            logger.info(f"PWM Actor {self.id} initialized successfully with initial power {self.initial_power}.")
        except Exception as e:
            logger.error(f"Failed to initialize PWM Actor {self.id}: {e}")

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

    async def run(self):
        while self.running:
            await asyncio.sleep(1)
            
@parameters([Property.Select(label="GPIO", options=ArduinoTypes['Mega']['digital_pins']), 
             Property.Select(label="Inverted", options=["Yes", "No"], description="No: Active on high; Yes: Active on low")])
class ArduinoGPIOActor(CBPiActor):
    async def on_start(self):
        self.gpio = int(self.props.get('GPIO', 0))
        self.inverted = self.props.get('Inverted', 'No') == 'Yes'
        self.state = False
        self.power = 0

        try:
            await board.set_pin_mode_digital_output(self.gpio)
            logger.info(f"Digital Actor {self.id} initialized on GPIO {self.gpio}")
        except Exception as e:
            logger.error(f"Failed to initialize Digital Actor {self.id} on GPIO {self.gpio}: {e}")

    async def on(self, power=None):
        try:
            digital_value = 0 if self.inverted else 1
            await board.digital_write(self.gpio, digital_value)
            self.state = True
            self.power = 255
            await self.cbpi.actor.actor_update(self.id, self.power)
            logger.info(f"Digital Actor {self.id} ON - GPIO {self.gpio} - Value {digital_value}")
        except Exception as e:
            logger.error(f"Failed to turn on Digital Actor {self.id} on GPIO {self.gpio}: {e}")

    async def off(self):
        try:
            digital_value = 1 if self.inverted else 0
            await board.digital_write(self.gpio, digital_value)
            self.state = False
            self.power = 0
            await self.cbpi.actor.actor_update(self.id, self.power)
            logger.info(f"Digital Actor {self.id} OFF - GPIO {self.gpio} - Value {digital_value}")
        except Exception as e:
            logger.error(f"Failed to turn off Digital Actor {self.id} on GPIO {self.gpio}: {e}")

    def get_state(self):
        return self.state

    @action("Set Power", parameters=[])
    async def setpower(self, **kwargs):
        if self.state:
            await self.on()
        else:
            await self.off()

    async def run(self):
        pass

def setup(cbpi):
    cbpi.plugin.register("ArduinoGPIOActor", ArduinoGPIOActor)
    cbpi.plugin.register("ArduinoGPIOPWMActor", ArduinoGPIOPWMActor)
    cbpi.plugin.register("ArduinoTelemetrix", ArduinoTelemetrix)