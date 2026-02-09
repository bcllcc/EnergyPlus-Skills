# Object Quick Reference

Top 50 most commonly used EnergyPlus object types. For full field details, use:
```
python idd_lookup.py "ObjectType"
```

## Simulation Control

### Version
One required. Must match EnergyPlus version.
```
Version, 23.2;
```

### SimulationControl
Controls what gets simulated (sizing, weather, etc.).
- Do Zone Sizing Calculation: Yes/No
- Do System Sizing Calculation: Yes/No
- Do Plant Sizing Calculation: Yes/No
- Run Simulation for Sizing Periods: Yes/No
- Run Simulation for Weather File Run Periods: Yes/No

### Building
Required. Building-level parameters.
- Name, North Axis (deg), Terrain (Country/Suburbs/City/Ocean/Urban)
- Loads Convergence Tolerance (W), Temperature Convergence Tolerance (deltaC)
- Solar Distribution, Max/Min Warmup Days

### Timestep
Timesteps per hour. Common values: 4, 6, 10. Higher = more accurate but slower.
```
Timestep, 6;
```

### RunPeriod
Simulation time period.
- Name, Begin Month, Begin Day, End Month, End Day
- Start Year (optional), Day of Week for Start Day

### SizingPeriod:DesignDay
Design conditions for HVAC sizing.
- Name, Month, Day, Day Type
- Max Dry-Bulb Temp, Dry-Bulb Range, Humidity Condition
- Wind Speed, Wind Direction

## Location & Climate

### Site:Location
- Name, Latitude (deg), Longitude (deg), Time Zone (hr), Elevation (m)

### Site:GroundTemperature:BuildingSurface
12 monthly ground temperatures (C) for floor heat transfer.

## Schedules

### ScheduleTypeLimits
Defines valid range for schedule values.
- Name, Lower Limit, Upper Limit, Numeric Type (Continuous/Discrete), Unit Type

### Schedule:Compact
Flexible schedule with day-type variations. Uses Through/For/Until syntax.
- Name, Schedule Type Limits Name, Field 1 (Through:), Field 2 (For:), Field 3 (Until:), ...

### Schedule:Constant
Single constant value for all time.
- Name, Schedule Type Limits Name, Hourly Value

## Materials

### Material
Full thermal property definition.
- Name, Roughness (VeryRough/Rough/MediumRough/MediumSmooth/Smooth/VerySmooth)
- Thickness (m), Conductivity (W/m-K), Density (kg/m3), Specific Heat (J/kg-K)
- Thermal Absorptance, Solar Absorptance, Visible Absorptance

### Material:NoMass
Defined by thermal resistance only (no thickness).
- Name, Roughness, Thermal Resistance (m2-K/W)

### Material:AirGap
Air gap defined by thermal resistance.
- Name, Thermal Resistance (m2-K/W)

### WindowMaterial:SimpleGlazingSystem
Simplified window properties.
- Name, U-Factor (W/m2-K), Solar Heat Gain Coefficient, Visible Transmittance

### WindowMaterial:Glazing
Detailed glazing layer properties.
- Name, Optical Data Type, Thickness, Solar/Visible Transmittance/Reflectance, IR properties

### WindowMaterial:Gas
Gas fill between glazing layers.
- Name, Gas Type (Air/Argon/Krypton/Xenon/Custom), Thickness (m)

## Constructions

### Construction
Layer assembly (outside to inside).
- Name, Outside Layer, Layer 2, Layer 3, ..., Inside Layer

## Geometry

### GlobalGeometryRules
Required. Defines coordinate conventions.
- Starting Vertex Position (UpperLeftCorner/LowerLeftCorner/UpperRightCorner/LowerRightCorner)
- Vertex Entry Direction (Counterclockwise/Clockwise)
- Coordinate System (Relative/World/Absolute)

### Zone
Thermal zone definition.
- Name, Direction of Relative North (deg), X/Y/Z Origin (m)
- Type (1=conditioned), Multiplier, Ceiling Height, Volume, Floor Area

### BuildingSurface:Detailed
Detailed surface geometry with vertices.
- Name, Surface Type (Floor/Wall/Ceiling/Roof), Construction Name, Zone Name
- Outside Boundary Condition (Outdoors/Ground/Surface/Adiabatic)
- Sun Exposure, Wind Exposure, Number of Vertices, Vertex coordinates (X,Y,Z)

### FenestrationSurface:Detailed
Window/door geometry.
- Name, Surface Type (Window/Door/GlassDoor), Construction Name
- Building Surface Name (parent wall), Number of Vertices, Vertex coordinates

### Shading:Building:Detailed
External shading surfaces (overhangs, fins).
- Name, Transmittance Schedule, Number of Vertices, Vertex coordinates

## Internal Loads

### People
Occupancy definition.
- Name, Zone Name, Number of People Schedule, Calculation Method (People/People/Area/Area/Person)
- Number/Density values, Fraction Radiant, Sensible Heat Fraction, Activity Level Schedule

### Lights
Lighting loads.
- Name, Zone Name, Schedule, Calculation Method (LightingLevel/Watts/Area/Watts/Person)
- Design Level values, Return Air Fraction, Fraction Radiant, Fraction Visible

### ElectricEquipment
Plug loads and equipment.
- Name, Zone Name, Schedule, Calculation Method
- Design Level values, Fraction Latent, Fraction Radiant, Fraction Lost

### ZoneInfiltration:DesignFlowRate
Air infiltration.
- Name, Zone Name, Schedule, Calculation Method (Flow/Zone/Flow/Area/Flow/ExteriorArea/AirChanges/Hour)
- Design Flow Rate, Constant/Temperature/Velocity/Wind Coefficients

## HVAC Templates (Simplified)

### HVACTemplate:Thermostat
Heating/cooling setpoint schedules.
- Name, Heating Setpoint Schedule, Constant Heating Setpoint
- Cooling Setpoint Schedule, Constant Cooling Setpoint

### HVACTemplate:Zone:BaseboardHeat
Baseboard heating for a zone.
- Zone Name, Template Thermostat Name, Zone Heating Sizing Factor
- Baseboard Heating Type (HotWater/Electric), Baseboard Heating Availability Schedule

### HVACTemplate:Zone:IdealLoadsAirSystem
Ideal loads for load calculation (no real HVAC).
- Zone Name, Template Thermostat Name, Availability Schedule
- Max Heating/Cooling Supply Air Temp, Heating/Cooling Limit

### HVACTemplate:Plant:HotWaterLoop
Hot water plant loop.
- Name, Pump Schedule, Pump Control Type, Hot Water Plant Operation Scheme

### HVACTemplate:Plant:Boiler
Boiler definition.
- Name, Boiler Type (HotWaterBoiler), Capacity, Efficiency, Fuel Type, Priority

## Sizing

### Sizing:Parameters
Global sizing factors.
- Heating Sizing Factor, Cooling Sizing Factor

### Sizing:Zone
Zone-level sizing parameters.
- Zone Name, Zone Cooling/Heating Design Supply Air Temp Method and values

## Output

### Output:Variable
Request specific output data.
- Key Value (* for all), Variable Name, Reporting Frequency

### Output:Meter
Request meter data.
- Key Name, Reporting Frequency

### Output:SQLite
Enable SQLite database output.
- Option Type: SimpleAndTabular

### Output:Table:SummaryReports
Enable summary report tables.
- Report 1 Name (AllSummary, AnnualBuildingUtilityPerformanceSummary, etc.)

### OutputControl:Table:Style
Report format.
- Column Separator (Comma/Tab/Fixed/HTML/SQLite/All)

### Output:VariableDictionary
Generate list of available variables.
- Key Field (Regular/IDF)

### Output:Surfaces:Drawing
Generate 3D geometry output.
- Report Type (DXF/DXF:WireFrame/VRML)
