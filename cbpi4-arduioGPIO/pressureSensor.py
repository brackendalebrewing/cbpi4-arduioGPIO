import os
import logging
import asyncio
import time
from cbpi.api import *
from cbpi.api.dataclasses import NotificationAction, NotificationType

logger = logging.getLogger(__name__)

@parameters([
    Property.Select(label="ADCPin", options=[1, 2, 3, 4, 5], description="Select the ADC pin (1-5)"),
    Property.Select("sensorType", options=["ADC",  "Pressure", "Liquid Level", "Volume"], description="Select which type of data to register for this sensor"),
    Property.Select("pressureType", options=["kPa", "PSI"]),
    Property.Number("adcLow", configurable=True, default_value=0, description="ADC value at minimum pressure, usually 0"),
    Property.Number("adcHigh", configurable=True, default_value=1024, description="ADC value at maximum pressure, usually 1024"),
    Property.Number("pressureLow", configurable=True, default_value=0, description="Pressure value at minimum ADC value, value in kPa"),
    Property.Number("pressureHigh", configurable=True, default_value=10, description="Pressure value at maximum ADC value, value in kPa"),
    Property.Number("sensorHeight", configurable=True, default_value=0, description="Location of Sensor from the bottom of the kettle in inches"),
    Property.Number("kettleDiameter", configurable=True, default_value=0, description="Diameter of kettle in inches"),
    Property.Select(label="Simulation Mode", options=["True", "False"], description="Enable simulation mode"),
    Property.Select(label="Volume Unit", options=["Gallons", "Liters"], description="Select the unit for volume measurement")
])
class PressureSensor(CBPiSensor):

    def __init__(self, cbpi, id, props):
        super(PressureSensor, self).__init__(cbpi, id, props)
        self.value = 0
        # ADC related properties
        self.adc_pin = int(props.get("ADCPin", 1))
        self.simulation_mode = str(props.get("Simulation Mode", "False")).lower() == "true"
        self.current_adc_value = 0
        
        # Initialize the simulated ADC value for the simulation mode
        self.simulated_adc_value = 0

        # Variables to be used with calculations
        self.GRAVITY = 9.807
        self.PI = 3.1415
        # Conversion values
        self.kpa_psi = 0.145
        self.bar_psi = 14.5038
        self.inch_mm = 25.4
        self.gallons_cubicinch = 231
        self.liters_cubicinch = 61.0237
        
        self.sensor_type = self.props.get("sensorType", "Liquid Level")
        self.sensorHeight = float(self.props.get("sensorHeight", 0))
        self.kettleDiameter = float(self.props.get("kettleDiameter", 0))
        self.pressureHigh = self.convert_pressure(int(self.props.get("pressureHigh", 10)))
        self.pressureLow = self.convert_pressure(int(self.props.get("pressureLow", 0)))
        self.volume_unit = self.props.get("Volume Unit", "Gallons")
        logger.info(f" **************************** Volume unit set to {self.volume_unit}")

        # Assuming the ADC range is from 0 to 1024
        self.adc_max = int(self.props.get("adcHigh", 1024))  # Maximum ADC value
        self.adc_min = int(self.props.get("adcLow", 0))     # Minimum ADC value

        # Calculate the linear conversion factors based on ADC values
        self.calcX = self.adc_max - self.adc_min
        self.calcM = (self.pressureHigh - self.pressureLow) / self.calcX
        self.calcB = self.pressureLow

    def convert_pressure(self, value):
        if self.props.get("pressureType", "kPa") == "PSI":
            return value * self.kpa_psi
        else:
            return value

    def convert_bar(self, value):
        if self.props.get("pressureType", "kPa") == "PSI":
            return value / self.bar_psi
        else:
            return value / 100

    async def on_start(self):
        if not self.simulation_mode:
            try:
                await TelemetrixAioService.initialize(self.cbpi.config.get)
                self.board = TelemetrixAioService.get_arduino_instance()
                await self.board.set_pin_mode_analog_input(self.adc_pin, 1, self.analog_callback)
                logger.info(f"ADC pin {self.adc_pin} initialized successfully")
            except Exception as e:
                logger.error(f"Failed to initialize ADC pin {self.adc_pin}: {str(e)}")
        else:
            logger.info("Pressure sensor running in simulation mode")

    async def analog_callback(self, data):
        self.current_adc_value = data[2]
        formatted_time = time.strftime('%Y-%m-%d %H:%M:%S', time.localtime(data[3]))
        logger.debug(f'Analog Callback: pin={data[1]}, Value={data[2]} Time={formatted_time}')

    async def read_adc(self):
        if self.simulation_mode:
            # Increment the simulated ADC value
            self.simulated_adc_value += 100

            # Ensure the value stays within the range of 0 to 1024
            if self.simulated_adc_value >= 1024:
                self.simulated_adc_value = 0
            logger.debug(f"simulated_adc_value--> {self.simulated_adc_value} ")
            return self.simulated_adc_value

        try:
            return self.current_adc_value
        except AttributeError:
            logger.error("ADC value not set by callback yet")
            return 0

    async def run(self):
        while self.running is True:
            try:
                adc_value = await self.read_adc()

                pressureValue = (self.calcM * adc_value) + self.calcB
                liquidLevel = self.calculate_liquid_level(pressureValue)
                volume = self.calculate_volume(liquidLevel)
                logger.info(f"run   Sensor {self.id} - liquid Vol liters--> {volume}") 
                
                

                sensor_type = self.props.get("sensorType", "Liquid Level")
                logger.info(f"run   Sensor type  {self.id} ---> {sensor_type}") 
                if sensor_type == "ADC":
                    self.value = adc_value
                elif sensor_type == "Pressure":
                    self.value = pressureValue
                elif sensor_type == "Liquid Level":
                    self.value = liquidLevel
                elif sensor_type == "Volume":
                    self.value = volume
                else:
                    self.value = adc_value  # Default to ADC

                self.push_update(self.value)
            except Exception as e:
                logger.error(f"ADC read error: {str(e)}")
                self.value = None
                self.push_update(self.value)

            await asyncio.sleep(1)

    def calculate_liquid_level(self, pressureValue):
        liquidLevel = ((self.convert_bar(pressureValue) / self.GRAVITY) * 100000) / self.inch_mm
        if liquidLevel > 0.49:
            liquidLevel += self.sensorHeight
        logger.debug(f"liquidLevel--> {liquidLevel} ")    
        return liquidLevel

    def calculate_volume(self, liquidLevel):
        kettleRadius = self.kettleDiameter / 2
        radiusSquared = kettleRadius * kettleRadius
        volumeCI = self.PI * radiusSquared * liquidLevel
        logger.info(f"  ******************* calculate_volume--> unit set to {self.volume_unit}")
        if self.volume_unit == "Liters":
            logger.debug(f"Sensor {self.id} - liquid Vol liters--> {volumeCI / self.liters_cubicinch}") 
            return volumeCI / self.liters_cubicinch
        else:
            logger.debug(f"Sensor {self.id} - liquid Vol gal--> {volumeCI / self.gallons_cubicinch}")
            return volumeCI / self.gallons_cubicinch

            
            
        
        

    def get_state(self):
        return dict(value=self.value)

    def reset(self):
        self.value = 0
        logger.info("Pressure sensor reset")
        return "OK"

def setup(cbpi):
    cbpi.plugin.register("PressureSensor", PressureSensor)
