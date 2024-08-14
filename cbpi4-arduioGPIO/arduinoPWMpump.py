import logging
import asyncio
import time
from cbpi.api import *
from cbpi.api.config import ConfigType
from cbpi.api.dataclasses import NotificationAction, NotificationType
from cbpi.api.dataclasses import Sensor, Kettle, Props
from .TelemetrixAioService import TelemetrixAioService
from pid import PID  # Assuming pid.py is in the same directory or properly installed

logger = logging.getLogger(__name__)

ArduinoTypes = {
    "Uno": {"digital_pins": list(range(14)), "pwm_pins": [3, 5, 6, 9, 10, 11], "name": "Uno"},
    "Nano": {"digital_pins": list(range(14)), "pwm_pins": [3, 5, 6, 9, 10, 11], "name": "Nano"},
    "Mega": {"digital_pins": list(range(54)), "pwm_pins": [2, 3, 4, 5, 6, 7, 8, 9, 10, 11, 12, 13], "name": "Mega"}
}


@parameters([
    Property.Select(label="GPIO", options=ArduinoTypes['Mega']['digital_pins']),
    Property.Number("Initial Flow", configurable=True, default_value=0),
    Property.Number("Kp", configurable=True, default_value=2.0),
    Property.Number("Ki", configurable=True, default_value=5.0),
    Property.Number("Kd", configurable=True, default_value=1.0),
    Property.Number("Time Base", configurable=True, default_value=1.0),  # Time base in seconds
    Property.Number("Power Base", configurable=True, default_value=255)  # Power base
])
class PumpActor(CBPiActor):

    async def on_start(self):
        self.initialized = False
        try:
            self.gpio = int(self.props.get('GPIO'))
            self.initial_flow = int(self.props.get('Initial Flow'))
            self.kp = self.props.get('Kp')
            self.ki = self.props.get('Ki')
            self.kd = self.props.get('Kd')
            self.time_base = self.props.get('Time Base')
            self.power_base = self.props.get('Power Base')

            board = TelemetrixAioService.get_arduino_instance()
            if not board:
                raise Exception("Arduino service not available")

            await board.set_pin_mode_analog_output(self.gpio)
            # Initialize the PID controller with the provided gains and setpoint
            self.pid = PID(Kp=self.kp, Ki=self.ki, Kd=self.kd, sample_time=self.time_base, output_limits=(0, self.power_base))
            self.pid.setpoint = self.initial_flow

            self.state = False
            self.power = self.initial_flow
            await self.cbpi.actor.actor_update(self.id, self.power)

            self.initialized = True
            logger.info(f"Pump Actor {self.id} initialized successfully on GPIO {self.gpio} with initial flow {self.initial_flow}.")
        except Exception as e:
            logger.error(f"Failed to initialize Pump Actor {self.id}: {e}")

    async def on(self, power=None):
        if not self.initialized:
            logger.error(f"Pump Actor {self.id} is not properly initialized.")
            return

        if power is not None:
            self.power = min(max(int(power), 0), self.power_base)
            self.pid.setpoint = self.power  # Update PID setpoint if power is provided directly
        else:
            self.power = self.initial_flow

        logger.info(f"Pump Actor {self.id} ON - GPIO {self.gpio} - Power {self.power}")
        board = TelemetrixAioService.get_arduino_instance()
        try:
            output = self.pid(self.power)  # Calculate the PID output
            await board.analog_write(self.gpio, output)
            self.state = True
            await self.cbpi.actor.actor_update(self.id, output)
        except Exception as e:
            logger.error(f"Failed to turn on Pump Actor {self.id} - GPIO {self.gpio}: {e}")

    async def off(self):
        if not self.initialized:
            logger.error(f"Pump Actor {self.id} is not properly initialized.")
            return

        logger.info(f"Pump Actor {self.id} OFF - GPIO {self.gpio}")
        board = TelemetrixAioService.get_arduino_instance()
        try:
            await board.analog_write(self.gpio, 0)
            self.state = False
            await self.cbpi.actor.actor_update(self.id, 0)
        except Exception as e:
            logger.error(f"Failed to turn off Pump Actor {self.id} - GPIO {self.gpio}: {e}")

    @action("Set Flow Rate", parameters=[Property.Number("Flow Rate", configurable=True, description="Set Flow Rate [0-255]")])
    async def set_flow_rate(self, Flow_Rate=255):
        """
        Action to set the flow rate of the pump.
        """
        if not self.initialized:
            logger.error(f"Pump Actor {self.id} is not properly initialized.")
            return

        self.power = min(max(int(Flow_Rate), 0), self.power_base)
        self.pid.setpoint = self.power  # Update PID setpoint

        logger.info(f"Pump Actor {self.id} Set Flow Rate - GPIO {self.gpio} - Flow Rate {self.power}")
        board = TelemetrixAioService.get_arduino_instance()
        try:
            output = self.pid(self.power)
            await board.analog_write(self.gpio, output)
            await self.cbpi.actor.actor_update(self.id, output)
        except Exception as e:
            logger.error(f"Failed to set flow rate for Pump Actor {self.id} - GPIO {self.gpio}: {e}")

    def get_state(self):
        return self.state

    async def run(self):
        while self.running:
            if self.initialized and self.state:
                # Implement any additional logic required during operation
                pass
            await asyncio.sleep(self.time_base)


@parameters([
    Property.Number(label="Volume", description="Volume limit for this step", configurable=True),
    Property.Actor(label="Actor", description="Actor to switch media flow on and off"),
    Property.Sensor(label="Sensor"),
    Property.Select(label="Reset", options=["Yes", "No"], description="Reset Flowmeter when done")
])
class ardunoPumpVolumeStep(CBPiStep):
    async def on_timer_done(self, timer):
        self.summary = ""
        self.cbpi.notify(self.name, f'Step finished. Transferred {round(self.current_volume, 2)} {self.unit}.', NotificationType.SUCCESS)
        if self.resetsensor == "Yes" and self.sensor and self.sensor.instance:
            await self.sensor.instance.reset()

        if self.actor is not None:
            await self.actor_off(self.actor)
        await self.next()

    async def on_timer_update(self, timer, seconds):
        await self.push_update()

    async def on_start(self):
        self.unit = self.cbpi.config.get("flowunit", "L")
        self.actor = self.props.get("Actor", None)
        self.target_volume = float(self.props.get("Volume", 0))
        self.flowsensor = self.props.get("Sensor", None)
        self.sensor = self.get_sensor(self.flowsensor)
        self.resetsensor = self.props.get("Reset", "Yes")

        if not self.sensor:
            logger.error(f"Sensor {self.flowsensor} not found.")
            self.cbpi.notify(self.name, f'Sensor {self.flowsensor} not found.', NotificationType.ERROR)
            await self.next()
            return

        if self.sensor.instance:
            await self.sensor.instance.reset()

        if self.timer is None:
            self.timer = Timer(1, on_update=self.on_timer_update, on_done=self.on_timer_done)

    async def on_stop(self):
        if self.timer is not None:
            await self.timer.stop()
        self.summary = ""
        if self.actor is not None:
            await self.actor_off(self.actor)
        await self.push_update()

    async def reset(self):
        self.timer = Timer(1, on_update=self.on_timer_update, on_done=self.on_timer_done)
        if self.actor is not None:
            await self.actor_off(self.actor)
        if self.resetsensor == "Yes" and self.sensor and self.sensor.instance:
            await self.sensor.instance.reset()

    async def run(self):
        if self.actor is not None:
            await self.actor_on(self.actor)
        self.summary = ""
        await self.push_update()
        while self.running:
            self.current_volume = self.get_sensor_value(self.flowsensor).get("value", 0)
            self.summary = f"Volume: {self.current_volume}"
            await self.push_update()

            if self.current_volume >= self.target_volume and not self.timer.is_running:
                logger.info("Target volume reached, starting timer.")
                self.timer.start()
                self.timer.is_running = True

            await asyncio.sleep(0.2)

        return StepResult.DONE


@parameters([
    Property.Number("Setpoint", configurable=True, default_value=18.0),
    Property.Number("Kp", configurable=True, default_value=2.0),
    Property.Number("Ki", configurable=True, default_value=5.0),
    Property.Number("Kd", configurable=True, default_value=1.0),
    Property.Number("Time Base", configurable=True, default_value=1.0),  # Time base in seconds
    Property.Number("Power Base", configurable=True, default_value=255),  # Power base

    Property.Sensor(label="Input Sensor", description="Wort Input Sensor"),
    Property.Sensor(label="Output Sensor", description="Wort Output Sensor"),
    Property.Sensor(label="Flow Sensor", description="Arduino Flow Sensor"),
    Property.Sensor(label="Volume Sensor", description="Arduino Volume Sensor"),
    Property.Actor(label="Pump Actor", description="Arduino Pump Actor"),
    Property.Number("Minimum Flow Threshold", configurable=True, default_value=1.0)
])
class arduinoPumpCoolStep(CBPiStep):

    async def on_start(self):
        self.setpoint = self.props.get("Setpoint")
        self.kp = self.props.get("Kp")
        self.ki = self.props.get("Ki")
        self.kd = self.props.get("Kd")
        self.unit = self.cbpi.config.get("flowunit", "L")
        self.input_temp_sensor_id = self.props.get("Input Sensor")
        self.output_temp_sensor_id = self.props.get("Output Sensor")
        self.flow_sensor_id = self.props.get("Flow Sensor")
        self.volume_sensor_id = self.props.get("Volume Sensor")
        self.pump_actor_id = self.props.get("Pump Actor")
        self.min_flow_threshold = self.props.get("Minimum Flow Threshold")

        if not self.output_temp_sensor_id:
            raise Exception("Output temperature sensor is required")

        # Use the new PID class
        self.pid = PID(Kp=self.kp, Ki=self.ki, Kd=self.kd, output_limits=(0, 255))
        self.pid.setpoint = self.setpoint

        self.input_temp_sensor = self.api.cache.get("sensors").get(self.input_temp_sensor_id)
        self.output_temp_sensor = self.api.cache.get("sensors").get(self.output_temp_sensor_id)
        self.flow_sensor = self.api.cache.get("sensors").get(self.flow_sensor_id)
        self.volume_sensor = self.api.cache.get("sensors").get(self.volume_sensor_id)
        self.pump_actor = self.api.cache.get("actors").get(self.pump_actor_id)

    async def execute(self):
        while self.is_running():
            try:
                output_temp = self.output_temp_sensor.instance.get_value()
                current_flow = self.flow_sensor.instance.get_value()
                current_volume = self.volume_sensor.instance.get_value()

                if self.input_temp_sensor and self.input_temp_sensor.instance:
                    input_temp = self.input_temp_sensor.instance.get_value()
                    temp_diff = input_temp - output_temp
                else:
                    temp_diff = 0

                pid_output = self.pid(temp_diff)

                if temp_diff < 0 and current_flow < self.min_flow_threshold:
                    pump_power = self.min_flow_threshold
                else:
                    pump_power = pid_output

                self.pump_actor.instance.set_power(pump_power)

                self.api.notify(headline="PID Control", message=f"Output Temp: {output_temp}, Flow: {current_flow}, Volume: {current_volume}, PID Output: {pid_output}, Pump Power: {pump_power}", timeout=None)

                await asyncio.sleep(0.1)
            except Exception as e:
                self.api.notify(headline="Execution Error", message=str(e), timeout=10)


def setup(cbpi):
    cbpi.plugin.register("PumpActor", PumpActor)
    cbpi.plugin.register("ardunoPumpVolumeStep", ardunoPumpVolumeStep)
    cbpi.plugin.register("arduinoPumpCoolStep", arduinoPumpCoolStep)
