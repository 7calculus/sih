# SurakshaLander — M1: Terrain & Data

Owns terrain preprocessing and the crater catalog for the SurakshaLander lunar rover simulation.

## What this module produces

| File | Description | Consumed by |
|---|---|---|
| `data/processed/slope.tif` | Terrain slope in degrees, per pixel | M4 (Planning) |
| `data/processed/roughness.tif` | Local terrain roughness (elevation std-dev, meters) | M4 (Planning) |
| `data/crater_db.sqlite` | Top 100 South Pole craters (lat, lon, diameter) | M2 (Localization) |

## Region covered
South Pole, ~80°S–90°S, polar stereographic projection, 608km × 608km, 20m/pixel.

## Setup

```bash
pip install rasterio numpy scipy pandas
```

## Getting the raw data (not included in this repo — see .gitignore)

1. **DEM**: Download a South Pole LOLA DEM tile (e.g. `south_pole_20m.tiff`) from
   `https://pgda.gsfc.nasa.gov/products/90`
   → save to `data/dem/south_pole_20m.tiff`

2. **Crater catalog**: Download `lunar_crater_database_robbins_2018.csv` from
   `https://pdsimage2.wr.usgs.gov/Individual_Investigations/moon_lro.kaguya_multi_craterdatabase_robbins_2018/data/`
   → save to `data/raw/lunar_crater_database_robbins_2018.csv`

## Running the pipeline

Run all commands from the project root:

```bash
python terrain/dem_loader.py      # sanity check: prints DEM shape/bounds
python terrain/slope.py           # writes data/processed/slope.tif
python terrain/roughness.py       # writes data/processed/roughness.tif
python terrain/build_crater_db.py # writes data/crater_db.sqlite
```

## Notes for M2 / M4

- Crater DB lat/lon is spherical coordinates; the DEM/slope/roughness rasters
  are in polar stereographic **meters**. A coordinate conversion is needed
  before matching crater positions to raster pixels.
- Slope/roughness rasters share the exact same shape, resolution, and bounds
  as the source DEM — no reprojection needed to overlay them with each other.