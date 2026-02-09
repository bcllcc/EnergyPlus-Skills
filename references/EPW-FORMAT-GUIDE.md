# EPW Weather File Format Guide

Source: EnergyPlus AuxiliaryPrograms.pdf, Section 2.9 (pages 55-74)

## File Structure

An EPW file is a simple ASCII comma-separated format:
- **8 header lines** (metadata)
- **8760 data lines** (365 days x 24 hours; 8784 if leap year)
- Lines do NOT end with semicolons (unlike IDF)
- Each data line has exactly **35 comma-separated values**

## Header Lines

### Line 1: LOCATION
```
LOCATION,<city>,<state>,<country>,<source>,<WMO>,<latitude>,<longitude>,<timezone>,<elevation>
```

| Field | Type | Units | Range | Notes |
|-------|------|-------|-------|-------|
| City | alpha | - | - | Location name |
| State/Province | alpha | - | - | Region code |
| Country | alpha | - | - | Country code |
| Source | alpha | - | - | Data source (TMY3, IWEC, CSWD, etc.) |
| WMO | alpha | - | 6 digits | World Meteorological Organization station number |
| Latitude | real | deg | -90.0 to +90.0 | + = North, - = South |
| Longitude | real | deg | -180.0 to +180.0 | + = East, - = West |
| TimeZone | real | hr | -12.0 to +12.0 | Relative to GMT |
| Elevation | real | m | -1000.0 to +9999.9 | Above sea level |

Example: `LOCATION,San Francisco Intl Ap,CA,USA,TMY3,724940,37.62,-122.40,-8.0,2.0`

### Line 2: DESIGN CONDITIONS
Contains ASHRAE HOF 2009 design conditions matched by WMO number.
Format: `DESIGN CONDITIONS,<N>,<source>,<heating fields...>,<cooling fields...>`
Complex variable-length record. Not typically edited manually.

### Line 3: TYPICAL/EXTREME PERIODS
```
TYPICAL/EXTREME PERIODS,<N>,<name1>,<type1>,<start1>,<end1>,...
```
Repeating groups of (Name, Type, StartDay, EndDay) for N periods.
Types: Typical (summer/winter/spring/autumn) and Extreme.

### Line 4: GROUND TEMPERATURES
```
GROUND TEMPERATURES,<N_depths>,<depth1>,<conductivity1>,<density1>,<specific_heat1>,<jan>,...,<dec>,...
```
For each depth: depth (m), soil conductivity (W/m-K), density (kg/m3),
specific heat (J/kg-K), then 12 monthly average temperatures (C).
Repeats for N depths (typically 3: 0.5m, 2m, 4m).

### Line 5: HOLIDAYS/DAYLIGHT SAVING
```
HOLIDAYS/DAYLIGHT SAVING,<LeapYear>,<DST_start>,<DST_end>,<N_holidays>,<name1>,<day1>,...
```
- LeapYear: Yes or No
- DST start/end: dates or blank
- Holiday pairs: name + date

### Lines 6-7: COMMENTS 1 and COMMENTS 2
```
COMMENTS 1,<text>
COMMENTS 2,<text>
```
Free-form text about data source and processing.

### Line 8: DATA PERIODS
```
DATA PERIODS,<N>,<records_per_hour>,<name>,<start_weekday>,<start_date>,<end_date>
```
- N: Number of data periods (typically 1)
- Records per hour: 1 for hourly data
- Start Day of Week: Sunday through Saturday
- Start/End dates: month/day format

Example: `DATA PERIODS,1,1,Data,Sunday, 1/ 1,12/31`

Important: A Run Period object may NOT cross Data Period boundary lines.

---

## Hourly Data Fields (35 per line)

Based on AuxiliaryPrograms.pdf Section 2.9, p.62-63.
**Bold** fields are used by EnergyPlus in calculations.

| Pos | ID | Field Name | Units | Min | Max | Missing | EP Used |
|-----|----|-----------|-------|-----|-----|---------|---------|
| 1 | N1 | Year | - | - | - | - | No |
| 2 | N2 | **Month** | - | 1 | 12 | Cannot be missing | Yes |
| 3 | N3 | **Day** | - | 1 | 31 | Cannot be missing | Yes |
| 4 | N4 | **Hour** | - | 1 | 24 | Cannot be missing | Yes |
| 5 | N5 | Minute | - | 1 | 60 | - | Yes |
| 6 | A1 | Data Source and Uncertainty Flags | - | - | - | - | Yes |
| 7 | N6 | **Dry Bulb Temperature** | C | >-70 | <70 | 99.9 | Yes |
| 8 | N7 | **Dew Point Temperature** | C | >-70 | <70 | 99.9 | Yes |
| 9 | N8 | **Relative Humidity** | % | 0 | 110 | 999 | Yes |
| 10 | N9 | **Atmospheric Station Pressure** | Pa | >31000 | <120000 | 999999 | Yes |
| 11 | N10 | Extraterrestrial Horizontal Radiation | Wh/m2 | 0 | - | 9999 | No |
| 12 | N11 | Extraterrestrial Direct Normal Radiation | Wh/m2 | 0 | - | 9999 | No |
| 13 | N12 | **Horizontal Infrared Radiation Intensity** | Wh/m2 | 0 | - | 9999 | Yes (1) |
| 14 | N13 | Global Horizontal Radiation | Wh/m2 | 0 | - | 9999 | No |
| 15 | N14 | **Direct Normal Radiation** | Wh/m2 | 0 | - | 9999 | Yes (2) |
| 16 | N15 | **Diffuse Horizontal Radiation** | Wh/m2 | 0 | - | 9999 | Yes (2) |
| 17 | N16 | Global Horizontal Illuminance | lux | 0 | - | 999999 (3) | No |
| 18 | N17 | Direct Normal Illuminance | lux | 0 | - | 999999 (3) | No |
| 19 | N18 | Diffuse Horizontal Illuminance | lux | 0 | - | 999999 (3) | No |
| 20 | N19 | Zenith Luminance | Cd/m2 | 0 | - | 9999 (4) | No |
| 21 | N20 | **Wind Direction** | deg | 0 | 360 | 999 | Yes |
| 22 | N21 | **Wind Speed** | m/s | 0 | 40 | 999 | Yes |
| 23 | N22 | **Total Sky Cover** | tenths | 0 | 10 | 99 | Yes |
| 24 | N23 | **Opaque Sky Cover** | tenths | 0 | 10 | 99 | Yes (5) |
| 25 | N24 | Visibility | km | - | - | 9999 | No |
| 26 | N25 | Ceiling Height | m | - | - | 99999 | No |
| 27 | N26 | **Present Weather Observation** | - | 0 | 9 | - | Yes |
| 28 | N27 | **Present Weather Codes** | - | 9 digits | - | - | Yes |
| 29 | N28 | Precipitable Water | mm | - | - | 999 | No |
| 30 | N29 | Aerosol Optical Depth | thousandths | - | - | .999 | No |
| 31 | N30 | **Snow Depth** | cm | - | - | 999 | Yes |
| 32 | N31 | Days Since Last Snowfall | days | - | - | 99 | No |
| 33 | N32 | Albedo | ratio | - | - | 999 | No |
| 34 | N33 | **Liquid Precipitation Depth** | mm | - | - | 999 | Yes |
| 35 | N34 | Liquid Precipitation Quantity | hr | - | - | 99 | No |

Notes:
1. If missing (>=9999), calculated from Opaque Sky Cover using formula below
2. If missing (>=9999) or invalid (<0), set to 0 by EnergyPlus
3. Will be considered missing if >= 999900
4. Will be considered missing if >= 9999
5. Used only to calculate Horizontal IR when field 13 is missing

---

## Hour Convention

Hour 1 = 00:01 to 01:00 (the data represents the **preceding** hour interval).
This means Hour 1 is the first hour of the day, ending at 01:00.

## Data Source and Uncertainty Flags (Field 6)

A consolidated text field combining source and uncertainty from various weather formats.
The flags use a compressed notation where `?` indicates uncertain/missing data.
Example: `?9?9?9?9E0?9?9?9?9?9?9?9?9?9?9?9?9?9?9?9*9*9?9?9?9`

This field is typically preserved as-is when editing EPW files.
When injecting measured data, use `?0?0?0?0?0?0?0?0?0?0?0?0?0?0?0?0?0?0?0?0?0?0?0?0`
(all zeros indicating measured/certain data).

## Missing Data Rules

When a field value >= its missing threshold:
- **Dry Bulb / Dew Point** (>=99.9): Substitute calculated or last good value
- **Direct / Diffuse Radiation** (>=9999 or <0): Set to 0
- **Horizontal IR** (>=9999): Calculate from Opaque Sky Cover (see formula)
- **Illuminance** (>=999900): Treated as missing
- General rule: EnergyPlus substitutes reasonable values or the last good value

## Horizontal IR Calculation Formula

When field 13 (Horizontal Infrared Radiation Intensity) is missing:

```
HorizontalIR = epsilon * sigma * T_drybulb^4

where:
  sigma = 5.6697e-8 W/m2-K4  (Stefan-Boltzmann constant)
  T_drybulb = dry bulb temperature in Kelvin (C + 273.15)

  epsilon = (0.787 + 0.764 * ln(T_dewpoint / 273)) * (1 + 0.0224*N - 0.0035*N^2 + 0.00028*N^3)

  T_dewpoint = dew point temperature in Kelvin
  N = opaque sky cover in tenths (field 24)
```

Reference: Walton (1983), Clark & Allen (1978)

## Present Weather Codes (Field 28)

A 9-character text field following TMY2 convention. Each position (1-9) represents
a different weather phenomenon:

| Position | Phenomenon | Key Values |
|----------|-----------|------------|
| 1 | Thunderstorm/Tornado/Squall | 0=Thunderstorm, 2=Tornado, 4=Squall, 9=None |
| 2 | Rain/Showers/Freezing Rain | 0=Light, 1=Moderate, 2=Heavy, 3-5=Showers, 6-8=Freezing, 9=None |
| 3 | Drizzle/Freezing Drizzle | 3=Light, 4=Moderate, 5=Heavy, 6-8=Freezing, 9=None |
| 4 | Snow/Snow Pellets/Ice Crystals | 0=Light, 1=Moderate, 2=Heavy, 3-5=Pellets, 6-8=Ice crystals, 9=None |
| 5 | Snow Showers/Squalls/Grains | 0=Light, 1-2=Showers, 3-5=Squalls, 6-7=Grains, 9=None |
| 6 | Sleet/Hail | 0-2=Ice pellets, 4=Hail, 9=None |
| 7 | Fog/Dust/Sand | 0=Fog, 1=Ice fog, 2=Ground fog, 3=Blowing dust, 4=Blowing sand, 5=Heavy fog, 9=None |
| 8 | Smoke/Haze/Blowing Snow | 0=Smoke, 1=Haze, 3=Dust, 4=Blowing snow, 5=Blowing spray, 9=None |
| 9 | Ice Pellets | 0=Light, 1=Moderate, 2=Heavy, 9=None |

Example: `929999999` = Heavy rain (position 2=2), no other phenomena (all 9s).

If Present Weather Observation (field 27) = 9, weather codes are considered missing.

## Liquid Precipitation Logic

- If Liquid Precipitation Depth (field 34) is not missing and >= 0.8 mm,
  EnergyPlus sets the rain indicator (IsRain) to true
- If the rain indicator shows rain but field 34 is missing/zero,
  precipitation is set to 2.0 mm as default

## Common Operation Patterns

These are typical use cases. The Agent should adapt to user-specific needs.

1. **Inject measured weather data**: Replace typical-year fields with measured values
   (Dry Bulb, Dew Point, Relative Humidity, radiation, wind, pressure)
2. **Modify specific periods**: Change temperature/radiation for specific dates
3. **Create extreme scenarios**: Shift temperatures for heat wave or cold snap analysis
4. **Climate change scenarios**: Apply uniform temperature offset (+2C, +4C)
5. **Generate new EPW from CSV**: Create complete EPW from raw measured data
6. **Extract statistics**: Monthly averages, degree days, peak conditions
7. **Compare weather files**: Side-by-side statistics of different EPW files

## Data Quality Considerations

- Always preserve the 8-line header structure
- Maintain exactly 35 comma-separated values per data line
- Do not modify field order
- When injecting measured data, update the Data Source Flags (field 6) accordingly
- Validate modified EPW files before using in simulation
- All units are SI (Celsius, Pa, Wh/m2, m/s, etc.)
- Hour=1 convention differs from midnight-based timestamps in measured data
