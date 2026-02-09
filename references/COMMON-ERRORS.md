# Common EnergyPlus Errors

## Diagnosis Strategy

1. Open the `.err` file (use `parse_outputs.py errors`)
2. Look for Fatal errors first (simulation stopped)
3. Read the error message and the `~~~` continuation lines
4. Identify the object name and line number mentioned
5. Check the IDF at that location
6. Fix and re-run

## Fatal Errors

### Missing Weather File
```
** Fatal  ** GetNextEnvironment: No more Coverage available
```
**Cause**: Annual simulation requested but no weather file provided.
**Fix**: Add `--weather <epw_file>` flag or switch to `--design-day`.

### IDD Version Mismatch
```
** Fatal  ** IP: IDF version does not match IDD version
```
**Cause**: IDF `Version` object doesn't match EnergyPlus version (23.2).
**Fix**: Update the Version object: `Version, 23.2;`

### Missing Required Object
```
** Fatal  ** Required Object "Building" not found
```
**Cause**: A required object is missing from the IDF.
**Fix**: Add the missing object (Building, Version, GlobalGeometryRules, etc.).

### HVACTemplate Without ExpandObjects
```
** Severe  ** IP: IDF line~NNNN Object=HVACTEMPLATE:...
** Fatal  ** IP: Errors occurred on processing IDF file
```
**Cause**: HVACTemplate objects present but `-x` flag not used.
**Fix**: Add `--expand-objects` flag to simulation command.

### Duplicate Object Names
```
** Fatal  ** Duplicate name found: ZONE_NAME
```
**Cause**: Two objects of the same type share the same name.
**Fix**: Rename one of the duplicate objects.

## Severe Errors

### Surface Geometry Issues
```
** Severe  ** GetSurfaceData: Surface=SURFACE_NAME has out-of-range vertices
```
**Cause**: Surface vertex coordinates are invalid (coplanar, zero-area, or self-intersecting).
**Fix**: Check and correct vertex coordinates. Ensure vertices are counterclockwise when viewed from outside.

### Node Connection Errors
```
** Severe  ** Node "NODE_NAME" did not find a matching component
```
**Cause**: HVAC nodes not properly connected (inlet/outlet mismatch).
**Fix**: Check HVACTemplate zone names match Zone object names exactly (case-sensitive).

### Construction Layer Issues
```
** Severe  ** Material/Construction "NAME" has zero thickness
```
**Cause**: Material thickness is 0 or construction has no layers.
**Fix**: Ensure all materials have positive thickness values.

### Convection Problems
```
** Severe  ** CalcHeatBalanceOutsideSurf: HTC <= 0
```
**Cause**: Heat transfer coefficient became zero or negative.
**Fix**: Check surface orientation, boundary conditions, and convection algorithm settings.

### SetpointManager Errors
```
** Severe  ** SetpointManager references unknown node
```
**Cause**: After HVACTemplate expansion, setpoint manager references a node that doesn't exist.
**Fix**: Check zone and thermostat names match exactly.

### Schedule Reference Errors
```
** Severe  ** Schedule "SCHEDULE_NAME" not found for People object
```
**Cause**: A load object (People, Lights, etc.) references a non-existent schedule.
**Fix**: Create the missing schedule or correct the name reference.

## Warnings

### Unmet Hours
```
** Warning ** Zone "ZONE_NAME" Heating Setpoint Not Met Time: NNN hours
```
**Cause**: HVAC system cannot meet the setpoint for some hours.
**Interpretation**:
- <50 hours/year: Generally acceptable
- 50-300 hours/year: May need investigation
- >300 hours/year: HVAC likely undersized

**Fix**: Increase HVAC capacity, check sizing parameters, or adjust setpoints.

### High Surface Temperatures
```
** Warning ** Very high surface temperature detected: NN.N C
```
**Cause**: Envelope issue (missing insulation, wrong material properties).
**Fix**: Check material thermal properties and construction layer order.

### Timestep Issues
```
** Warning ** Plant loop exceeding capacity
** Warning ** TimestepTooLarge
```
**Cause**: Simulation timestep too large for the HVAC system dynamics.
**Fix**: Increase `Timestep` from 4 to 6 or more per hour.

### Zone Air Heat Balance
```
** Warning ** Zone Air Heat Balance Percent Error exceeded tolerance
```
**Cause**: Convergence issues in heat balance calculation.
**Fix**:
1. Increase `Timestep` (e.g., from 4 to 6)
2. Check for extreme material properties
3. Reduce convergence tolerance in Building object

## HVACTemplate-Specific Pitfalls

1. **Zone name mismatch**: HVACTemplate zone names must exactly match Zone object names
2. **Thermostat naming**: Thermostat must be defined before being referenced by zone templates
3. **Missing plant loop**: Zone heating/cooling templates require corresponding plant loop templates
4. **Forgetting `-x` flag**: Most common mistake - always check for HVACTemplate objects first

## Quick Troubleshooting Checklist

- [ ] Version object matches EnergyPlus version (23.2)?
- [ ] All referenced objects exist (constructions, materials, schedules, zones)?
- [ ] Names are exactly case-matched?
- [ ] HVACTemplate detected? Using `-x` flag?
- [ ] Annual run? Weather file provided?
- [ ] Surface geometry valid (non-zero area, correct vertex order)?
- [ ] All objects properly terminated with semicolon?
