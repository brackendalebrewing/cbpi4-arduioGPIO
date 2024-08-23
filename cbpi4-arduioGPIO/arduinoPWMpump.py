import logging
import asyncio
import time
from cbpi.api import *
from cbpi.api import CBPiActor, CBPiExtension, Property, action, parameters
from cbpi.api.config import ConfigType
from cbpi.api.dataclasses import NotificationAction, NotificationType
from cbpi.api.dataclasses import Sensor, Kettle, Props
from .TelemetrixAioService import TelemetrixAioService
from .pid import PID  # Assuming pid.py is in the same directory or properly installed

from .shared import flowmeter_data 


logger = logging.getLogger(__name__)

ArduinoTypes = {
    "Uno": {"digital_pins": list(range(14)), "pwm_pins": [3, 5, 6, 9, 10, 11], "name": "Uno"},
    "Nano": {"digital_pins": list(range(14)), "pwm_pins": [3, 5, 6, 9, 10, 11], "name": "Nano"},
    "Mega": {"digital_pins": list(range(54)), "pwm_pins": [2, 3, 4, 5, 6, 7, 8, 9, 10, 11, 12, 13], "name": "Mega"}
}
# Assuming the global dictionary is defined in the same module or imported
# from your flowmeter module
# from your_module import flowmeter_data

@parameters([
    Property.Select(label="GPIO", options=ArduinoTypes['Mega']['pwm_pins']),
    Property.Number(label="Initial Power", configurable=True, description="Initial PWM Power (0-255)", default_value=0),
    Property.Number(label="MaxOutput", configurable=True, description="Max Output Value", default_value=255),
    Property.Text(label="Flowmeter Sensor ID", configurable=True, description="Enter Flowmeter Sensor ID"),
    Property.Number("Kp", configurable=True, default_value=2.0),
    Property.Number("Ki", configurable=True, default_value=5.0),
    Property.Number("Kd", configurable=True, default_value=1.0),
    Property.Number("Time Base", configurable=True, default_value=1.0)  # Time base in seconds
])
class SimplePumpActor(CBPiActor):
    def __init__(self, cbpi, id, props):
        super().__init__(cbpi, id, props)
        self.gpio = int(self.props['GPIO'])
        self.initial_power = int(self.props['Initial Power'])
        self.maxoutput = int(self.props.get("MaxOutput", 255))  # Default to 255 if not specified
        self.flowmeter_id = self.props['Flowmeter Sensor ID']  # Store the Flowmeter Sensor ID entered by the user
        self.kp = float(self.props.get("Kp", 2.0))
        self.ki = float(self.props.get("Ki", 5.0))
        self.kd = float(self.props.get("Kd", 1.0))
        self.time_base = float(self.props.get("Time Base", 1.0))

        self.power = 0
        self.output = 0
        self.state = False

        # Initialize the PID controller once
        self.pid = PID(self.kp, self.ki, self.kd, setpoint=2)
        self.pid.sample_time = self.time_base
        self.pid.output_limits = (0, self.maxoutput)

        logger.debug(f"Initialized SimplePumpActor: gpio={self.gpio}, initial_power={self.initial_power}, maxoutput={self.maxoutput}, flowmeter_id={self.flowmeter_id}")

    def calculate_pid_output(self, flow_rate, setpoint):
        """
        Calculate the PID output based on the current flow rate.

        :param flow_rate: The current flow rate (measured variable)
        :param setpoint: The desired flow rate (target value)
        :return: The output control variable
        """
        # Update the setpoint
        self.pid.setpoint = setpoint

        # Calculate the output using the current flow rate
        output = self.pid(float(flow_rate))
        #output = 175 #self.pid( float(flow_rate) )

        # Info-level logging to track the PID calculation process
        logger.info(f"PID Calculation: setpoint={setpoint}, flow_rate={flow_rate}")
        logger.info(f"PID Constants: Kp={self.kp}, Ki={self.ki}, Kd={self.kd}, Time Base={self.time_base}")
        logger.info(f"PID Output: {output} (Output range: 0-{self.maxoutput})")

        return output

    @action("Set Power", parameters=[Property.Number(label="Power", configurable=True, description="Power Setting [0-100]")])
    async def setpower(self, Power, **kwargs):
        self.power = int(Power)
        if self.power < 0:
            self.power = 0
        if self.power > 100:
            self.power = 100
        self.output = round(self.maxoutput * self.power / 100)
        await self.set_power(self.output)
        logger.debug(f"setpower: power={self.power}, output={self.output}")

    @action("Set Output", parameters=[Property.Number(label="Output", configurable=True, description="Output Setting [0-MaxOutput]")])
    async def setoutput(self, Output, **kwargs):
        self.output = int(Output)
        if self.output < 0:
            self.output = 0
        if self.output > self.maxoutput:
            self.output = self.maxoutput
        await self.set_output(self.output)
        logger.info(f"setoutput: power={self.power}, output={self.output}")

    async def on_start(self):
        board = TelemetrixAioService.get_arduino_instance()
        try:
            await board.set_pin_mode_analog_output(self.gpio)
            self.power = self.initial_power
            self.output = round(self.maxoutput * self.power / 100)
            self.state = False
            await self.cbpi.actor.actor_update(self.id, self.power)
            logger.info(f"PWM Actor {self.id} initialized successfully with initial power {self.initial_power} and flowmeter ID {self.flowmeter_id}.")
        except Exception as e:
            logger.error(f"Failed to initialize PWM Actor {self.id}: {e}")

    async def on(self, power=None, output=None):
        if power is not None:
            if power != self.power:
                power = min(100, power)
                power = max(0, power)
                self.power = round(power)
        if output is not None:
            if output != self.output:
                output = min(self.maxoutput, output)
                output = max(0, output)
                self.output = round(output)
        self.state = True
        logger.info(f"PWM ACTOR {self.id} ON - GPIO {self.gpio} - Power {self.power}% - Output {self.output}")
        board = TelemetrixAioService.get_arduino_instance()
        try:
            await board.analog_write(self.gpio, self.output)
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

    async def set_power(self, output):
        logger.info(f"Setting power for PWM ACTOR {self.id} - GPIO {self.gpio} to {output}")
        board = TelemetrixAioService.get_arduino_instance()
        try:
            await board.analog_write(self.gpio, output)
            await self.cbpi.actor.actor_update(self.id, round(100 * output / self.maxoutput))
            logger.info(f"PWM Actor {self.id} power set to {output}.")
        except Exception as e:
            logger.error(f"Failed to set power for PWM GPIO {self.gpio}: {e}")

    async def set_output(self, output):
        self.output = round(output)
        self.power = round(self.output / self.maxoutput * 100)
        if self.state is True:
            await self.on(self.power, self.output)
        else:
            await self.off()
        await self.cbpi.actor.actor_update(self.id, self.power, self.output)

    def get_state(self):
        logger.debug(f"get_state called, returning {self.state}")
        return self.state

    async def run(self):
        logger.debug("Entering run loop")
        while self.running:
            try:
                # Fetch the flow rate from the global dictionary using the flowmeter ID
                flow_rate = flowmeter_data.get(self.flowmeter_id, None)
                setpoint = 10 
                if flow_rate is not None:
                    logger.info(f"Flow Rate--> {flow_rate} L/min")
                    pid_output = self.calculate_pid_output(float(flow_rate),float( setpoint) )
                    await self.set_output(pid_output)
                else:
                    logger.warning(f"No data available for Sensor ID {self.flowmeter_id}")
            except Exception as e:
                logger.error(f"Failed to retrieve flow rate for Sensor ID {self.flowmeter_id}: {e}")
            
            logger.debug(f"Running loop: state={self.state}, power={self.power}, output={self.output}, flow_rate={flow_rate}")
            await asyncio.sleep(1)

@parameters([
    Property.Select(label="Power GPIO", options=ArduinoTypes['Mega']['digital_pins']),
    Property.Number("Initial Flow", configurable=True, default_value=0),
    Property.Number("Kp", configurable=True, default_value=2.0),
    Property.Number("Ki", configurable=True, default_value=5.0),
    Property.Number("Kd", configurable=True, default_value=1.0),
    Property.Number("Time Base", configurable=True, default_value=1.0),  # Time base in seconds
    Property.Number("MaxOutput", configurable=True, default_value=255),  # MaxOutput parameter for finer control
    Property.Text(label="Flow Meter Sensor ID", configurable=True, description="Enter the ID of the Flow Meter sensor to use")  # Flow meter sensor ID
])
class PumpActor(CBPiActor):

    async def on_start(self):
        self.initialized = False
        try:
            self.power_gpio = int(self.props.get('Power GPIO'))
            self.initial_flow = float(self.props.get('Initial Flow'))
            self.kp = float(self.props.get('Kp'))
            self.ki = float(self.props.get('Ki'))
            self.kd = float(self.props.get('Kd'))
            self.time_base = float(self.props.get('Time Base'))
            self.maxoutput = int(self.props.get('MaxOutput', 255))  # Initialize MaxOutput
            self.flow_meter_sensor_id = self.props.get('Flow Meter Sensor ID')  # Get flow meter sensor ID from the text field

            board = TelemetrixAioService.get_arduino_instance()
            if not board:
                raise Exception("Arduino service not available")

            await board.set_pin_mode_analog_output(self.power_gpio)

            # Initialize the PID controller with the provided gains and setpoint
            self.pid = PID(Kp=self.kp, Ki=self.ki, Kd=self.kd, sample_time=self.time_base, output_limits=(0, self.maxoutput))
            self.pid.setpoint = self.initial_flow

            self.state = False
            self.output = self.initial_flow
            await self.cbpi.actor.actor_update(self.id, self.output)

            self.initialized = True
            logger.info(f"Pump Actor {self.id} initialized successfully on Power GPIO {self.power_gpio} with initial flow {self.initial_flow}.")
        except Exception as e:
            logger.error(f"Failed to initialize Pump Actor {self.id}: {e}")

    async def on(self, power=None, output=None):
        if not self.initialized:
            logger.error(f"Pump Actor {self.id} is not properly initialized.")
            return

        if output is not None:
            output = min(self.maxoutput, float(output))
            output = max(0, output)
            self.output = round(output)
        elif power is not None:
            power = min(100, float(power))
            power = max(0, power)
            self.power = round(power)
            self.output = int(self.power * self.maxoutput / 100)  # Convert power percentage to output value

        board = TelemetrixAioService.get_arduino_instance()
        try:
            # Set the PWM output to the desired level
            await board.analog_write(self.power_gpio, self.output)
            self.state = True  # Set state to True when the pump is turned on
            await self.cbpi.actor.actor_update(self.id, self.output)
            logger.info(f"Pump Actor {self.id} ON - Power GPIO {self.power_gpio} - Output {self.output}")
        except Exception as e:
            logger.error(f"Failed to turn on Pump Actor {self.id} - Power GPIO {self.power_gpio}: {e}")

    async def off(self):
        if not self.initialized:
            logger.error(f"Pump Actor {self.id} is not properly initialized.")
            return

        logger.info(f"Pump Actor {self.id} OFF - Power GPIO {self.power_gpio}")
        board = TelemetrixAioService.get_arduino_instance()
        try:
            # Set the PWM output to 0 to stop the pump
            await board.analog_write(self.power_gpio, 0)
            self.state = False  # Set state to False when the pump is turned off
            await self.cbpi.actor.actor_update(self.id, 0)
        except Exception as e:
            logger.error(f"Failed to turn off Pump Actor {self.id} - Power GPIO {self.power_gpio}: {e}")

    @action("Set Flow Rate", parameters=[Property.Number(label="Flow_Rate", configurable=True, description="Set Flow Rate [0-MaxOutput]")])
    async def set_flow_rate(self, Flow_Rate=None):
        """
        Action to set the flow rate of the pump.
        """
        if not self.initialized:
            logger.error(f"Pump Actor {self.id} is not properly initialized.")
            return

        try:
            # Convert Flow_Rate to float, ensuring it's within valid bounds
            if Flow_Rate is not None:
                Flow_Rate = float(Flow_Rate)
            else:
                Flow_Rate = float(self.initial_flow)

            self.output = min(max(int(Flow_Rate), 0), self.maxoutput)
            self.pid.setpoint = self.output  # Update PID setpoint

            logger.info(f"Pump Actor {self.id} Set Flow Rate - Power GPIO {self.power_gpio} - Output {self.output} / MaxOutput {self.maxoutput}")
            board = TelemetrixAioService.get_arduino_instance()
            
            output = self.pid(int(self.output))
            await board.analog_write(self.power_gpio, int(self.output))
            await self.cbpi.actor.actor_update(self.id, int(self.output))
        except Exception as e:
            logger.error(f"Failed to set flow rate for Pump Actor {self.id} - Power GPIO {self.power_gpio}: {e}")

    def get_state(self):
        return self.state

    async def run(self):
        while self.running:
            if self.initialized and self.state:
                # Access the flow rate data from the global dictionary using the flowmeter ID
                try:
                    current_flow = flowmeter_data.get(self.flow_meter_sensor_id, None)
                    if current_flow is not None:
                        # Calculate the new output using the PID controller
                        self.output = self.pid(float(current_flow))
                        self.output = max(0, min(int(self.output), self.maxoutput))  # Clamp output

                        board = TelemetrixAioService.get_arduino_instance()
                        await board.analog_write(self.power_gpio, self.output)
                        await self.cbpi.actor.actor_update(self.id, self.output)
                        logger.info(f"Pump Actor {self.id} adjusting output to {self.output} based on flow rate {current_flow}.")
                    else:
                        logger.warning(f"No data available for Sensor ID {self.flow_meter_sensor_id}")
                except Exception as e:
                    logger.error(f"Failed to adjust pump output based on flow meter input for Pump Actor {self.id}: {e}")
            else:
                logger.debug(f"Pump Actor {self.id} is not active (state={self.state}), skipping output adjustment.")
        
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
    Property.Number("MaxOutput", configurable=True, default_value=255),  # MaxOutput parameter for finer control

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
        self.maxoutput = int(self.props.get("MaxOutput", 255))  # Initialize MaxOutput

        if not self.output_temp_sensor_id:
            raise Exception("Output temperature sensor is required")

        # Use the new PID class
        self.pid = PID(Kp=self.kp, Ki=self.ki, Kd=self.kd, output_limits=(0, self.maxoutput))
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

                # Set pump power based on the PID output and MaxOutput
                self.pump_actor.instance.set_power(pump_power)

                self.api.notify(headline="PID Control", message=f"Output Temp: {output_temp}, Flow: {current_flow}, Volume: {current_volume}, PID Output: {pid_output}, Pump Power: {pump_power}", timeout=None)

                await asyncio.sleep(0.1)
            except Exception as e:
                self.api.notify(headline="Execution Error", message=str(e), timeout=10)


def setup(cbpi):
    cbpi.plugin.register("PumpActor", PumpActor)
    cbpi.plugin.register("ardunoPumpVolumeStep", ardunoPumpVolumeStep)
    cbpi.plugin.register("arduinoPumpCoolStep", arduinoPumpCoolStep)
