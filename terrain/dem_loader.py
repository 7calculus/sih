import rasterio
import numpy as np
from pathlib import Path
from rasterio.enums import Resampling

PROJECT_ROOT = Path(__file__).resolve().parents[1]

def load_dem(path=None, max_size=None):
    """
    Loads a DEM GeoTIFF and returns the elevation array + metadata.
    """
    if path is None:
        path = PROJECT_ROOT / "data" / "Lunar_Map.tiff"
    with rasterio.open(path) as src:
        scale = 1.0
        if max_size and max(src.height, src.width) > max_size:
            scale = max(src.height, src.width) / max_size
            out_height = max(1, round(src.height / scale))
            out_width = max(1, round(src.width / scale))
            elevation = src.read(
                1,
                out_shape=(out_height, out_width),
                resampling=Resampling.average,
            ).astype(np.float32)
        else:
            elevation = src.read(1).astype(np.float32)
        meta = src.meta.copy()
        if scale != 1.0:
            meta.update(
                height=elevation.shape[0],
                width=elevation.shape[1],
                transform=src.transform * src.transform.scale(scale, scale),
            )
        bounds = src.bounds
        pixel_size = (src.res[0] * scale, src.res[1] * scale)

    # Handle common nodata sentinel values in LOLA products
    nodata_val = meta.get("nodata")
    if nodata_val is not None:
        elevation[elevation == nodata_val] = np.nan

    print(f"Loaded DEM: shape={elevation.shape}, pixel_size={pixel_size}, bounds={bounds}")
    return elevation, meta, pixel_size


if __name__ == "__main__":
    elevation, meta, pixel_size = load_dem()
    print("Min elevation:", np.nanmin(elevation))
    print("Max elevation:", np.nanmax(elevation))