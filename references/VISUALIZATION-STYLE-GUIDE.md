# Visualization Style Guide

Professional chart standards for building energy analysis.

## Design Philosophy

- `visualize_results.py` provides 6 preset chart types as shortcuts — not limits
- The Agent is encouraged to write custom matplotlib code for any chart type
- All charts must be **engineering-report quality**: clear, labeled, professional
- When in doubt, choose clarity over decoration

---

## Color Palette

### Primary Colors (Semantic)

| Role | Hex | Usage |
|------|-----|-------|
| Heating / Hot | `#E53935` | Heating energy, high temperature |
| Cooling / Cold | `#1E88E5` | Cooling energy, low temperature |
| Primary accent | `#4285F4` | Default single-series, links |
| Success / Pass | `#43A047` | Calibration pass, within limits |
| Warning | `#FB8C00` | Caution, near threshold |
| Fail / Error | `#E53935` | Calibration fail, exceeded |
| Neutral | `#757575` | Grid, secondary text, reference lines |

### Multi-Series Palette (8 distinguishable colors)

For parametric comparisons, multi-zone plots, and stacked charts:

```python
SERIES_COLORS = [
    "#4285F4",  # blue
    "#EA4335",  # red
    "#FBBC04",  # yellow
    "#34A853",  # green
    "#FF6D01",  # orange
    "#46BDC6",  # teal
    "#7B1FA2",  # purple
    "#C2185B",  # pink
]
```

Alternative: `plt.cm.Set2` for <=8 series (consistent with existing scripts).

### Colormaps

| Chart type | Colormap | Rationale |
|------------|----------|-----------|
| Temperature heatmap | `RdYlBu_r` | Red=hot, blue=cold, intuitive |
| Energy intensity | `YlOrRd` | Low=yellow, high=red |
| Solar radiation | `YlOrRd` | Matches irradiance convention |
| Humidity | `BuGn` | Blue-green, moisture association |
| Generic sequential | `viridis` | Perceptually uniform, colorblind safe |

### Colorblind-Safe Alternative

When accessibility is required, replace `SERIES_COLORS` with:

```python
CB_SAFE = ["#0072B2", "#D55E00", "#009E73", "#CC79A7",
           "#F0E442", "#56B4E9", "#E69F00", "#000000"]
```

Source: Wong (2011), Nature Methods.

---

## Typography

### Font Priority

```python
plt.rcParams["font.sans-serif"] = ["Microsoft YaHei", "SimHei",
                                    "Arial", "Helvetica", "DejaVu Sans"]
plt.rcParams["axes.unicode_minus"] = False
```

### Size Hierarchy

| Element | Size (pt) | Weight |
|---------|-----------|--------|
| Title | 13-14 | bold |
| Subtitle / annotation | 10-11 | normal |
| Axis label | 10-11 | normal |
| Tick label | 8-9 | normal |
| Legend | 9 | normal |
| Value annotation | 8 | normal |

---

## Layout

### Figure Sizes

| Type | Size (inches) | Usage |
|------|---------------|-------|
| Single chart | (10, 6) | Standard time-series, bar chart |
| Comparison / dual panel | (12, 8) | Calibration overlay + residuals |
| Multi-panel | (12, 4*N) | N stacked subplots |
| Horizontal bar | (10, max(4, N*0.5+1)) | Parametric comparison (N variants) |
| Heatmap | (12, 6) | 24h x 365d or 24h x 12m |

### Margins and Spacing

```python
plt.tight_layout(pad=1.5)     # default
plt.subplots_adjust(hspace=0.3)  # for multi-panel
```

### Axes Background

```python
plt.rcParams["figure.facecolor"] = "white"
plt.rcParams["axes.facecolor"] = "#F8F9FA"  # light gray
```

### Grid

```python
ax.grid(axis="y", alpha=0.3, linestyle="--")  # default: y-axis only
ax.grid(alpha=0.3, linestyle="--")             # both axes when needed
```

### Legend Placement

Priority order:
1. Upper-right corner (default) — `loc="upper right"`
2. Outside right — `bbox_to_anchor=(1.02, 1)` when legend overlaps data
3. Below chart — `bbox_to_anchor=(0.5, -0.15), loc="upper center"` for many items

---

## Data Annotations

### Extreme Values

Mark peak/minimum points on time-series:

```python
max_idx = values.index(max(values))
ax.annotate(f"Peak: {values[max_idx]:.1f}",
            xy=(x[max_idx], values[max_idx]),
            xytext=(10, 10), textcoords="offset points",
            fontsize=8, arrowprops=dict(arrowstyle="->", color="#757575"))
```

### Reference Lines

```python
# Average line
ax.axhline(y=mean_val, color="#757575", linestyle="--", linewidth=0.8,
           label=f"Mean: {mean_val:.1f}")

# Threshold (e.g., comfort upper limit)
ax.axhline(y=26, color="#E53935", linestyle=":", linewidth=1,
           label="Comfort limit (26 C)")
```

### Bar Value Labels

```python
for bar in bars:
    ax.text(bar.get_x() + bar.get_width()/2, bar.get_height(),
            f"{bar.get_height():.1f}", ha="center", va="bottom", fontsize=8)
```

---

## Chart Type Best Practices

### Temperature Time-Series

- Use dual Y-axis when combining indoor temp + outdoor temp or solar radiation
- Left Y: temperature (C), Right Y: radiation (W/m2) or outdoor temp
- Indoor temperature: solid line, outdoor: dashed line
- Mark heating/cooling setpoint as horizontal reference lines

### Energy Comparison (Parametric)

- Horizontal bar chart: variant names on Y-axis for readability
- Sort by value (ascending or descending) for quick visual ranking
- Add value labels at bar ends
- Use consistent color when comparing same metric, varied colors for different metrics

### Calibration Plot

- Top panel: time-series overlay (measured=blue, simulated=red/orange)
- Bottom panel: residuals (bar chart, color by magnitude)
- Always include R2 and CV(RMSE) in annotation or title

### Heatmap (8760 Data)

- X-axis: hours (0-23), Y-axis: days or months
- Use `RdYlBu_r` for temperature, `YlOrRd` for energy/radiation
- Include colorbar with units
- Consider monthly aggregation (12x24) if annual detail is too dense

### Scatter Plot (Simulated vs Measured)

- Add 45-degree reference line (perfect agreement)
- Annotate R2 value
- Use alpha=0.5 for overlapping points

---

## Output

- Format: PNG
- Resolution: 150 DPI (default), 300 DPI for publication
- File naming: `{description}_{chart_type}.png`
  - Examples: `calibration_comparison.png`, `window_ufactor_peak_heating.png`

```python
plt.savefig(path, dpi=150, bbox_inches="tight", facecolor="white")
plt.close()
```

---

## Quick Template

Minimal boilerplate for custom charts:

```python
import matplotlib
matplotlib.use("Agg")
import matplotlib.pyplot as plt

fig, ax = plt.subplots(figsize=(10, 6))

# --- plot data ---
ax.plot(x, y, color="#4285F4", linewidth=1.5, label="Series")

# --- formatting ---
ax.set_xlabel("Time", fontsize=11)
ax.set_ylabel("Temperature (C)", fontsize=11)
ax.set_title("Chart Title", fontsize=13, fontweight="bold")
ax.legend(loc="upper right", fontsize=9)
ax.grid(axis="y", alpha=0.3, linestyle="--")

plt.tight_layout()
plt.savefig("output.png", dpi=150, bbox_inches="tight")
plt.close()
```
