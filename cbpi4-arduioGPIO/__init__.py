import asyncio
import logging
from cbpi.api import CBPiActor, CBPiExtension, Property, action, parameters
from .TelemetrixAioService import TelemetrixAioService
from .FlowMeters import ADCFlowVolumeSensor, FlowStep, Flowmeter_Config  # Import the flow meter classes

from .arduinoPWMpump import PumpActor,ardunoPumpVolumeStep,arduinoPumpCoolStep



logger = logging.getLogger(__name__)

# Define Arduino types
ArduinoTypes = {
    "Uno": {"digital_pins": list(range(14)), "pwm_pins": [3, 5, 6, 9, 10, 11], "name": "Uno"},
    "Nano": {"digital_pins": list(range(14)), "pwm_pins": [3, 5, 6, 9, 10, 11], "name": "Nano"},
    "Mega": {"digital_pins": list(range(54)), "pwm_pins": [2, 3, 4, 5, 6, 7, 8, 9, 10, 11, 12, 13], "name": "Mega"}
}

class ArduinoTelemetrix(CBPiExtension):
    def __init__(self, cbpi):
        self.cbpi = cbpi
        self._task = asyncio.create_task(self.init_actor())

    async def init_actor(self):
        await TelemetrixAioService.init_service(self.cbpi)
        await resave_and_reload_gpio_actors(self.cbpi)

async def resave_and_reload_gpio_actors(cbpi):
    try:
        gpio_actors = [actor for actor in cbpi.actor.data if isinstance(actor.instance, (ArduinoGPIOActor, ArduinoGPIOPWMActor))]
        for actor in gpio_actors:
            logging.info(f"Processing Actor {actor.id}")
            await actor.instance.on_start()
        await cbpi.actor.save()
        logging.info(f"Successfully processed {len(gpio_actors)} GPIO actors.")
    except Exception as e:
        logging.error(f"Error processing GPIO actors: {str(e)}")
        raise

@parameters([
    Property.Select(label="GPIO", options=ArduinoTypes['Mega']['pwm_pins']), 
    Property.Number(label="Initial Power", configurable=True, description="Initial PWM Power (0-255)", default_value=0)
])
class ArduinoGPIOPWMActor(CBPiActor):
    @action("Set Power", parameters=[Property.Number(label="Power", configurable=True, description="Power Setting [0-255]")])
    async def setpower(self, Power, **kwargs):
        self.power = min(max(int(Power), 0), 255)
        await self.set_power(self.power)

    async def on_start(self):
        self.gpio = int(self.props['GPIO'])
        self.initial_power = int(self.props['Initial Power'])
        board = TelemetrixAioService.get_arduino_instance()
        try:
            await board.set_pin_mode_analog_output(self.gpio)
            self.power = self.initial_power
            self.state = False
            await self.cbpi.actor.actor_update(self.id, self.power)
            logger.info(f"PWM Actor {self.id} initialized successfully with initial power {self.initial_power}.")
        except Exception as e:
            logger.error(f"Failed to initialize PWM Actor {self.id}: {e}")

    async def on(self, power):
        if power is not None:
            self.power = power
        else:
            self.power = self.initial_power
        logger.info(f"PWM ACTOR {self.id} ON - GPIO {self.gpio} - Power {self.power}")
        board = TelemetrixAioService.get_arduino_instance()
        try:
            await board.analog_write(self.gpio, self.power)
            self.state = True
            await self.cbpi.actor.actor_update(self.id, self.power)
        except Exception as e:
            logger.error(f"Failed to turn on PWM GPIO {self.gpio}: {e}")

    async def off(self):
        logger.info(f"PWM ACTOR {self.id} OFF - GPIO {self.gpio}")
        board = TelemetrixAioService.get_arduino_instance()
        try:
            await board.analog_write(self.gpio, 0)
            self.state = False
        except Exception as e:
            logger.error(f"Failed to turn off PWM GPIO {self.gpio}: {e}")
            
    async def set_power(self, power):
        logging.info(" ***************** ArduinoGPIOPWMActor **************** ")
        #if 1==1:
        board = TelemetrixAioService.get_arduino_instance()
        logging.info(" ***************** ArduinoGPIOPWMActor # 2 **************** ")
        try:
            await board.analog_write(self.gpio, int(power))
            await self.cbpi.actor.actor_update(self.id, int(power))
            logger.info(f"PWM Actor power change {self.id} initialized successfully with initial power {self.initial_power}.")
        except Exception as e:
            logger.error(f"Failed to set power for PWM GPIO {self.gpio}: {e}")


    def get_state(self):
        return self.state

    async def run(self):
        while self.running:
            await asyncio.sleep(1)

@parameters([
    Property.Select(label="GPIO", options=ArduinoTypes['Mega']['digital_pins']), 
    Property.Select(label="Inverted", options=["Yes", "No"], description="No: Active on high; Yes: Active on low")
])
class ArduinoGPIOActor(CBPiActor):
    
    async def setpower(self, Power=255, **kwargs):
        self.power = min(max(int(Power), 0), 255)
        await self.set_power(self.power)

    def get_GPIO_state(self, state):
        if state == 1:
            return 1 if self.inverted == False else 0
        if state == 0:
            return 0 if self.inverted == False else 1

    async def on_start(self):
        self.gpio = int(self.props['GPIO'])
        self.inverted = True if self.props.get("Inverted", "No") == "Yes" else False
        self.power = 255
        board = TelemetrixAioService.get_arduino_instance()
        try:
            await board.set_pin_mode_digital_output(self.gpio)
            self.state = False
            await self.cbpi.actor.actor_update(self.id, self.power)
        except Exception as e:
            logger.error(f"Failed to initialize GPIO Actor {self.id}: {e}")

    async def on(self, power):
        if power is not None:
            self.power = power
        else:
            self.power = 255
        logger.info(f"GPIO ACTOR {self.id} ON - GPIO {self.gpio} - Power {self.power}")
        board = TelemetrixAioService.get_arduino_instance()
        try:
            await board.digital_write(self.gpio, self.power)
            self.state = True
            await self.cbpi.actor.actor_update(self.id, self.power)
        except Exception as e:
            logger.error(f"Failed to turn on GPIO GPIO {self.gpio}: {e}")

    async def off(self):
        logger.info(f"GPIO ACTOR {self.id} OFF - GPIO {self.gpio}")
        board = TelemetrixAioService.get_arduino_instance()
        try:
            await board.digital_write(self.gpio, 0)
            self.state = False
        except Exception as e:
            logger.error(f"Failed to turn off GPIO GPIO {self.gpio}: {e}")

    async def set_power(self, power):
        if self.state:
            board = TelemetrixAioService.get_arduino_instance()
            try:
                await board.digital_write(self.gpio, int(power))
                await self.cbpi.actor.actor_update(self.id, int(power))
            except Exception as e:
                logger.error(f"Failed to set power for GPIO GPIO {self.gpio}: {e}")

    def get_state(self):
        return self.state

    async def run(self):
        while self.running:
            await asyncio.sleep(1)

def setup(cbpi):
    cbpi.plugin.register("ArduinoGPIOActor", ArduinoGPIOActor)
    cbpi.plugin.register("ArduinoGPIOPWMActor", ArduinoGPIOPWMActor)
    cbpi.plugin.register("ArduinoTelemetrix", ArduinoTelemetrix)
    cbpi.plugin.register("Flowmeter_Config", Flowmeter_Config)  # Register Flowmeter Config
    cbpi.plugin.register("ADCFlowVolumeSensor", ADCFlowVolumeSensor)  # Register ADC Flow Volume Sensor
    cbpi.plugin.register("FlowStep", FlowStep)  # Register Flow Step
    
    cbpi.plugin.register("PumpActor", PumpActor)
    cbpi.plugin.register("ardunoPumpVolumeStep", ardunoPumpVolumeStep)
    cbpi.plugin.register("arduinoPumpCoolStep", arduinoPumpCoolStep)
    
    cbpi.register_on_startup(lambda: asyncio.create_task(resave_and_reload_gpio_actors(cbpi)))
