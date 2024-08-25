# -*- coding: utf-8 -*-
import os
import logging
import asyncio
from cbpi.api import *
from cbpi.api.dataclasses import NotificationAction, NotificationType


logger = logging.getLogger(__name__)

@parameters([
    Property.Select(label="ADCPin", options=[1, 2, 3, 4, 5], description="Select the ADC pin (1-5)"),
    Property.Select("sensorType", options=["Voltage", "Digits", "Pressure", "Liquid Level", "Volume"], description="Select which type of data to register for this sensor"),
    Property.Select("pressureType", options=["kPa", "PSI"]),
    Property.Number("voltLow", configurable=True, default_value=0, description="Pressure Sensor minimum voltage, usually 0"),
    Property.Number("voltHigh", configurable=True, default_value=5, description="Pressure Sensor maximum voltage, usually 5"),
    Property.Number("pressureLow", configurable=True, default_value=0, description="Pressure value at minimum voltage, value in kPa"),
    Property.Number("pressureHigh", configurable=True, default_value=10, description="Pressure value at maximum voltage, value in kPa"),
    Property.Number("sensorHeight", configurable=True, default_value=0, description="Location of Sensor from the bottom of the kettle in inches"),
    Property.Number("kettleDiameter", configurable=True, default_value=0, description="Diameter of kettle in inches")
])
class PressureSensor(CBPiSensor):

    def __init__(self, cbpi, id, props):
        super(PressureSensor, self).__init__(cbpi, id, props)
        self.value = 0
        # Variables to be used with calculations
        self.GRAVITY = 9.807
        self.PI = 3.1415
        # Conversion values
        self.kpa_psi = 0.145
        self.bar_psi = 14.5038
        self.inch_mm = 25.4
        self.gallons_cubicinch = 231

        self.sensorHeight = float(self.props.get("sensorHeight", 0))
        self.kettleDiameter = float(self.props.get("kettleDiameter", 0))
        self.ADCPin = int(self.props.get("ADCPin", 1))
        self.pressureHigh = self.convert_pressure(int(self.props.get("pressureHigh", 10)))
        self.pressureLow = self.convert_pressure(int(self.props.get("pressureLow", 0)))

        self.calcX = int(self.props.get("voltHigh", 5)) - int(self.props.get("voltLow", 0))
        self.calcM = (self.pressureHigh - self.pressureLow) / self.calcX
        self.calcB = 0
        if int(self.props.get("voltLow", 0)) > 0:
            self.calcB = (-1 * int(self.props.get("voltLow", 0))) * self.calcM
    
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

    def dummy_adc_read(self):
        # This dummy function returns a fixed value of 123
        return 12

    async def run(self):
        while self.running is True:
            try:
                adc_value = self.dummy_adc_read()

                pressureValue = (self.calcM * adc_value) + self.calcB
                liquidLevel = self.calculate_liquid_level(pressureValue)
                volume = self.calculate_volume(liquidLevel)

                sensor_type = self.props.get("sensorType", "Liquid Level")
                if sensor_type == "Voltage":
                    self.value = adc_value
                elif sensor_type == "Pressure":
                    self.value = pressureValue
                elif sensor_type == "Liquid Level":
                    self.value = liquidLevel
                elif sensor_type == "Volume":
                    self.value = volume
                else:
                    self.value = adc_value  # Default to voltage

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
        return liquidLevel

    def calculate_volume(self, liquidLevel):
        kettleRadius = self.kettleDiameter / 2
        radiusSquared = kettleRadius * kettleRadius
        volumeCI = self.PI * radiusSquared * liquidLevel
        return volumeCI / self.gallons_cubicinch

    def get_state(self):
        return dict(value=self.value)


def setup(cbpi):
    cbpi.plugin.register("PressureSensor", PressureSensor)
    pass
