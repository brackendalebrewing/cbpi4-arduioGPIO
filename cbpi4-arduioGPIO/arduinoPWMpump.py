import logging
import time
import asyncio
from cbpi.api import *
from cbpi.api.config import ConfigType
from cbpi.api.dataclasses import NotificationAction, NotificationType
from cbpi.api.dataclasses import Sensor, Kettle, Props
from .TelemetrixAioService import TelemetrixAioService

logger = logging.getLogger(__name__)
import logging
import asyncio
import time
from cbpi.api import *
from cbpi.api.base import CBPiBase
from cbpi.api.dataclasses import NotificationAction, NotificationType

logger = logging.getLogger(__name__)



@parameters([
    Property.Select(label="GPIO", options=[1,2,3,4,5,6]),
    Property.Number("Initial Flow", configurable=True, default_value=0),
    Property.Number("Kp", configurable=True, default_value=2.0),
    Property.Number("Ki", configurable=True, default_value=5.0),
    Property.Number("Kd", configurable=True, default_value=1.0),
    Property.Number("Time Base", configurable=True, default_value=1.0),  # Time base in seconds
    Property.Number("Power Base", configurable=True, default_value=255)  # Power base
])
class PumpActor(CBPiActor):

    #@action("Set Power", parameters=[Property.Number("Power", configurable=True, description="Power Setting [0-255]")])
    async def setpower(self, Power=255, **kwargs):
        power = min(max(int(Power), 0), self.power_base)
        await self.set_power(power)

    async def on_start(self):
        self.initialized = False
        try:
            self.gpio = int(self.props.get('GPIO'))
            self.initial_flow = int(self.props.get('Initial Flow'))
            self.kp = (self.props.get('Kp'))
            self.ki = (self.props.get('Ki'))
            self.kd = (self.props.get('Kd'))
            self.time_base = (self.props.get('Time Base'))
            self.power_base = (self.props.get('Power Base'))

            board = TelemetrixAioService.get_arduino_instance()
            if not board:
                raise Exception("Arduino service not available")

            await board.set_pin_mode_analog_output(self.gpio)
            self.pid = PID(self.kp, self.ki, self.kd, self.time_base)
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
        else:
            self.power = self.initial_flow

        logger.info(f"Pump Actor {self.id} ON - GPIO {self.gpio} - Power {self.power}")
        board = TelemetrixAioService.get_arduino_instance()
        try:
            await board.analog_write(self.gpio, self.power)
            self.state = True
            await self.cbpi.actor.actor_update(self.id, self.power)
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

    async def set_power(self, power):
        if not self.initialized:
            logger.error(f"Pump Actor {self.id} is not properly initialized.")
            return

        power = min(max(int(power), 0), self.power_base)
        if self.state:
            board = TelemetrixAioService.get_arduino_instance()
            try:
                await board.analog_write(self.gpio, power)
                self.power = power
                await self.cbpi.actor.actor_update(self.id, power)
            except Exception as e:
                logger.error(f"Failed to set power for Pump Actor {self.id} - GPIO {self.gpio}: {e}")

    def get_state(self):
        return self.state

    async def run(self):
        while self.running:
            if self.initialized and self.state:
                # Here you can implement PID control logic if needed
                pass
            await asyncio.sleep(self.time_base)

class PID:
    def __init__(self, P, I, D, time_base):
        self.Kp = P
        self.Ki = I
        self.Kd = D
        self.SetPoint = 0.0
        self.sample_time = time_base
        self.current_time = time.time()
        self.last_time = self.current_time
        self.clear()
    
    def clear(self):
        self.SetPoint = 0.0
        self.PTerm = 0.0
        self.ITerm = 0.0
        self.DTerm = 0.0
        self.last_error = 0.0
        self.int_error = 0.0
        self.windup_guard = 20.0
        self.output = 0.0
    
    def compute(self, feedback_value):
        error = self.SetPoint - feedback_value
        self.current_time = time.time()
        delta_time = self.current_time - self.last_time
        delta_error = error - self.last_error
        
        if delta_time >= self.sample_time:
            self.PTerm = self.Kp * error
            self.ITerm += error * delta_time
            
            if self.ITerm < -self.windup_guard:
                self.ITerm = -self.windup_guard
            elif self.ITerm > self.windup_guard:
                self.ITerm = self.windup_guard
            
            self.DTerm = 0.0
            if delta_time > 0:
                self.DTerm = delta_error / delta_time
            
            self.last_time = self.current_time
            self.last_error = error
            self.output = self.PTerm + (self.Ki * self.ITerm) + (self.Kd * self.DTerm)
        
        return self.output

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

    Property.Sensor(label="Input Sensor",description="Wort Input Sensor"),
    Property.Sensor(label="Output Sensor",description="Wort Output Sensor"),
    Property.Sensor(label="Flow Sensor",description="Arduino Flow Sensor"),
    Property.Sensor(label="Volume Sensor",description="Arduino Volume  Sensor"),
    Property.Actor(label="Pump Actor", description="Arduino Pump Actor"),
    Property.Number("Minimum Flow Threshold", configurable=True, default_value=1.0)
])



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

        # Check if output temperature sensor exists
        if not self.output_temp_sensor_id:
            raise Exception("Output temperature sensor is required")

        self.pid = PID(self.kp, self.ki, self.kd)
        self.pid.SetPoint = self.setpoint

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
                
                # Check if input temperature sensor exists
                if self.input_temp_sensor and self.input_temp_sensor.instance:
                    input_temp = self.input_temp_sensor.instance.get_value()
                    temp_diff = input_temp - output_temp
                else:
                    # If input temperature sensor doesn't exist, use a default value or alternative calculation
                    temp_diff = 0  # or some other default value
                
                pid_output = self.pid.compute(temp_diff)
                
                # If temperature is overshooting, ensure minimum flow threshold
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