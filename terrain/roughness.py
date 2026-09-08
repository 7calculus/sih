import numpy as np
import rasterio
from pathlib import Path
from scipy.ndimage import uniform_filter
from dem_loader import load_dem

PROJECT_ROOT = Path(__file__).resolve().parents[1]

def compute_roughness(elevation, window_size=3):
    """
    Fast vectorized roughness: local std = sqrt(E[X^2] - (E[X])^2)
    """
    elev = np.nan_to_num(elevation, nan=0.0)
    mean = uniform_filter(elev, size=window_size)
    mean_sq = uniform_filter(elev**2, size=window_size)
    variance = np.clip(mean_sq - mean**2, 0, None)  # avoid tiny negatives from float error
    roughness = np.sqrt(variance)
    return roughness.astype(np.float32)



def save_roughness(roughness, meta, out_path=None):
    out_path = Path(out_path) if out_path else PROJECT_ROOT / "data" / "processed" / "roughness.tif"
    out_path.parent.mkdir(parents=True, exist_ok=True)
    meta_out = meta.copy()
    meta_out.update(dtype="float32", count=1, nodata=np.nan)

    with rasterio.open(out_path, "w", **meta_out) as dst:
        dst.write(roughness, 1)

    print(f"Saved roughness map to {out_path}")


if __name__ == "__main__":
    elevation, meta, pixel_size = load_dem(max_size=1024)
    roughness = compute_roughness(elevation, window_size=3)
    save_roughness(roughness, meta)

    print("Roughness min/max:", np.nanmin(roughness), np.nanmax(roughness))