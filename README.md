# SurakshaLander — M1: Terrain & Data

This module owns terrain preprocessing and the crater catalog for the
SurakshaLander lunar rover navigation simulation. It produces the offline
data files that M2 (Localization) and M4 (Planning) depend on.

---

## Outputs Produced by This Module

| File | What it is | Consumed by |
|---|---|---|
| `data/processed/slope.tif` | Terrain slope in degrees, per pixel (0° = flat, up to ~70° at crater rims/steep terrain) | M4 (Planning) |
| `data/processed/roughness.tif` | Local terrain roughness — elevation std-dev in a moving window, in meters | M4 (Planning) |
| `data/crater_db.sqlite` | Top 100 South Pole craters (id, latitude, longitude, diameter) | M2 (Localization) |

**Region covered:** Lunar South Pole, approximately 80°S–90°S, polar
stereographic projection, ~608km × 608km tile, 20m/pixel resolution.

**Important for M2/M4:** the crater DB stores plain lat/lon (spherical
coordinates), while the DEM/slope/roughness rasters are in polar
stereographic **meters**. A coordinate conversion is required before
matching a crater's position to a pixel in the raster files. `slope.tif`
and `roughness.tif` share the exact same shape, resolution, and bounds
as the source DEM, so they overlay directly with each other.

---

## Setup

```bash
pip install rasterio numpy scipy pandas
```

---

## 1. Get the Raw Data (not included in this repo — see `.gitignore`)

### DEM (elevation tile)
1. Go to `https://pgda.gsfc.nasa.gov/products/90`
2. Download a South Pole LOLA DEM GeoTIFF (e.g. `south_pole_20m.tiff`)
3. Save it to `data/dem/south_pole_20m.tiff`

### Crater catalog
1. Go to `https://pdsimage2.wr.usgs.gov/Individual_Investigations/moon_lro.kaguya_multi_craterdatabase_robbins_2018/data/`
2. Download `lunar_crater_database_robbins_2018.csv`
3. Save it to `data/raw/lunar_crater_database_robbins_2018.csv`

---

## 2. Run the Pipeline

Run all commands from the **project root** (not from inside `terrain/`):

```bash
python terrain/dem_loader.py       # sanity check — prints DEM shape/bounds/elevation range
python terrain/slope.py            # generates data/processed/slope.tif
python terrain/roughness.py        # generates data/processed/roughness.tif
python terrain/build_crater_db.py  # generates data/crater_db.sqlite
```

Expected result after all four run successfully:
data/dem/south_pole_20m.tiff (raw input, downloaded manually — not in git)
data/processed/slope.tif (generated)
data/processed/roughness.tif (generated)
data/crater_db.sqlite (generated)


**Note:** the large `.tif`/`.tiff` files and raw `.csv` are excluded
from this repo via `.gitignore` (GitHub's file size limits). You must
regenerate them locally using the steps above, or ask a teammate to
share the generated files directly outside of git.

---

## 3. Verify the Outputs

```python
import rasterio
import numpy as np

for name in ["slope", "roughness"]:
    with rasterio.open(f"data/processed/{name}.tif") as src:
        arr = src.read(1)
        print(f"{name}.tif — shape: {arr.shape}, min: {np.nanmin(arr):.2f}, "
              f"max: {np.nanmax(arr):.2f}, mean: {np.nanmean(arr):.2f}")
```

Sanity-check ranges (South Pole terrain):
- `slope.tif` — roughly `0°` to `70°`
- `roughness.tif` — small positive values, low single digits on average

```bash
sqlite3 data/crater_db.sqlite "SELECT COUNT(*) FROM craters;"
```
Should return `100` (or fewer if the South Pole latitude cutoff was
too strict for the region covered).

---

## File Structure
terrain/
├── dem_loader.py # Loads the DEM GeoTIFF, returns elevation array + metadata
├── slope.py # Computes slope.tif from the DEM
├── roughness.py # Computes roughness.tif from the DEM
└── build_crater_db.py # Filters Robbins catalog → crater_db.sqlite

data/
├── dem/ # Raw DEM tile (not tracked in git)
├── raw/ # Raw crater CSV (not tracked in git)
├── processed/ # Generated slope.tif, roughness.tif (not tracked in git)
└── crater_db.sqlite # Generated crater DB (tracked in git — small file)