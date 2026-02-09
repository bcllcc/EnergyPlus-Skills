# IDF Editing Guide

## IDF File Syntax

### Basic Rules
- Each object starts with the object type name followed by a comma
- Fields are separated by commas
- The last field of an object ends with a semicolon (`;`)
- Comments start with `!` (user comments) or `!-` (auto-generated)
- Empty/optional fields: leave blank but include the comma placeholder
- All alpha fields are limited to 100 characters
- Numeric fields are double-precision floating point

### Object Format
```
ObjectType,
    field_value_1,            !- Field Name 1
    field_value_2,            !- Field Name 2
    last_field_value;         !- Last Field Name
```

### Section Headers
IDF files use comment headers to organize objects:
```
!-   ===========  ALL OBJECTS IN CLASS: OBJECTNAME ===========
```

### Key Syntax Patterns
- **Keywords**: Case-insensitive (e.g., `Yes`, `yes`, `YES` are equivalent)
- **Autosize**: Enter `Autosize` for autosizable numeric fields
- **Autocalculate**: Enter `Autocalculate` for autocalculatable fields
- **Blank fields**: Just a comma (`,`) - uses the default value if one is defined

## Common Object Editing Patterns

### Adding Materials

```
Material,
    NewMaterial,              !- Name
    MediumRough,              !- Roughness
    0.1,                      !- Thickness {m}
    1.0,                      !- Conductivity {W/m-K}
    1800,                     !- Density {kg/m3}
    900,                      !- Specific Heat {J/kg-K}
    0.9,                      !- Thermal Absorptance
    0.7,                      !- Solar Absorptance
    0.7;                      !- Visible Absorptance
```

No-mass material (for air gaps, insulation by R-value):
```
Material:NoMass,
    AirGap,                   !- Name
    Rough,                    !- Roughness
    0.18;                     !- Thermal Resistance {m2-K/W}
```

Window glazing (simple):
```
WindowMaterial:SimpleGlazingSystem,
    SimpleWindow,             !- Name
    2.0,                      !- U-Factor {W/m2-K}
    0.4;                      !- Solar Heat Gain Coefficient
```

### Defining Constructions

Layers are listed outside-to-inside:
```
Construction,
    ExteriorWall,             !- Name
    ExteriorFinish,           !- Outside Layer
    Insulation,               !- Layer 2
    ConcreteBlock,            !- Layer 3
    InteriorFinish;           !- Layer 4 (Inside Layer)
```

### Schedule:Compact Syntax

Format: `Through: date, For: day-type, Until: time, value`
```
Schedule:Compact,
    OccupancySchedule,       !- Name
    Fraction,                 !- Schedule Type Limits Name
    Through: 12/31,           !- Field 1
    For: Weekdays,            !- Field 2
    Until: 08:00, 0.0,        !- Fields 3-4
    Until: 18:00, 1.0,        !- Fields 5-6
    Until: 24:00, 0.0,        !- Fields 7-8
    For: AllOtherDays,        !- Field 9
    Until: 24:00, 0.0;        !- Fields 10-11
```

Day types: `Weekdays`, `Weekends`, `Holidays`, `SummerDesignDay`, `WinterDesignDay`, `AllDays`, `AllOtherDays`

### Adding a Zone

```
Zone,
    NewZone,                  !- Name
    0,                        !- Direction of Relative North {deg}
    0, 0, 0,                  !- Origin X, Y, Z {m}
    1,                        !- Type (1=conditioned)
    1;                        !- Multiplier
```

### Adding Building Surfaces

```
BuildingSurface:Detailed,
    Wall-1,                   !- Name
    Wall,                     !- Surface Type (Floor/Wall/Ceiling/Roof)
    ExteriorWall,             !- Construction Name
    NewZone,                  !- Zone Name
    ,                         !- Space Name
    Outdoors,                 !- Outside Boundary Condition
    ,                         !- Outside Boundary Condition Object
    SunExposed,               !- Sun Exposure
    WindExposed,              !- Wind Exposure
    ,                         !- View Factor to Ground
    4,                        !- Number of Vertices
    0, 0, 3,                  !- Vertex 1 {m}
    0, 0, 0,                  !- Vertex 2 {m}
    10, 0, 0,                 !- Vertex 3 {m}
    10, 0, 3;                 !- Vertex 4 {m}
```

Surface types: `Floor`, `Wall`, `Ceiling`, `Roof`
Boundary conditions: `Outdoors`, `Ground`, `Surface`, `Adiabatic`
Vertex order: Counterclockwise when viewed from outside

### Adding Windows

```
FenestrationSurface:Detailed,
    Window-1,                 !- Name
    Window,                   !- Surface Type (Window/Door/GlassDoor)
    SimpleWindow,             !- Construction Name
    Wall-1,                   !- Building Surface Name
    ,                         !- Outside Boundary Condition Object
    ,                         !- View Factor to Ground
    ,                         !- Frame and Divider Name
    1,                        !- Multiplier
    4,                        !- Number of Vertices
    1, 0, 2.5,                !- Vertex 1
    1, 0, 0.8,                !- Vertex 2
    4, 0, 0.8,                !- Vertex 3
    4, 0, 2.5;                !- Vertex 4
```

### Configuring Outputs

Output:Variable (specific variable at key):
```
Output:Variable,
    *,                        !- Key Value (* = all zones)
    Zone Mean Air Temperature,!- Variable Name
    Hourly;                   !- Reporting Frequency
```

Output:SQLite (enable SQL database):
```
Output:SQLite,
    SimpleAndTabular;         !- Option Type
```

Output:Table:SummaryReports:
```
Output:Table:SummaryReports,
    AllSummary;               !- Report 1 Name
```

Reporting frequencies: `Timestep`, `Hourly`, `Daily`, `Monthly`, `RunPeriod`, `Environment`, `Annual`

### Internal Loads

People:
```
People,
    Zone1-People,             !- Name
    NewZone,                  !- Zone Name
    OccupancySchedule,       !- Number of People Schedule Name
    People,                   !- Number of People Calculation Method
    4,                        !- Number of People
    ,                         !- People per Floor Area
    ,                         !- Floor Area per Person
    0.3,                      !- Fraction Radiant
    Autocalculate;            !- Sensible Heat Fraction
```

Lights:
```
Lights,
    Zone1-Lights,             !- Name
    NewZone,                  !- Zone Name
    LightingSchedule,         !- Schedule Name
    Watts/Area,               !- Design Level Calculation Method
    ,                         !- Lighting Level {W}
    10,                       !- Watts per Zone Floor Area {W/m2}
    ,                         !- Watts per Person {W/person}
    0,                        !- Return Air Fraction
    0.42,                     !- Fraction Radiant
    0.18;                     !- Fraction Visible
```

## Tips

1. **Always use `idd_lookup.py`** to check field definitions before editing
2. **Names are case-sensitive** - `Zone 1` and `zone 1` are different
3. **Field order matters** - fields must appear in the order defined by the IDD
4. **Validate after every edit** using `idf_helper.py validate`
5. **Check references** - ensure Construction, Zone, Schedule names match exactly
