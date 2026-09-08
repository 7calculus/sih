import numpy as np
import rasterio
from pathlib import Path
from dem_loader import load_dem

PROJECT_ROOT = Path(__file__).resolve().parents[1]

def compute_slope(elevation, pixel_size):
    """
    Computes slope in degrees at each pixel using a gradient method.
    """
    dx, dy = pixel_size  # meters per pixel in x and y

    grad_y, grad_x = np.gradient(elevation, dy, dx)
    slope_rad = np.arctan(np.sqrt(grad_x**2 + grad_y**2))
    slope_deg = np.degrees(slope_rad)

    return slope_deg.astype(np.float32)


def save_slope(slope_deg, meta, out_path=None):
    out_path = Path(out_path) if out_path else PROJECT_ROOT / "data" / "processed" / "slope.tif"
    out_path.parent.mkdir(parents=True, exist_ok=True)
    meta_out = meta.copy()
    meta_out.update(dtype="float32", count=1, nodata=np.nan)

    with rasterio.open(out_path, "w", **meta_out) as dst:
        dst.write(slope_deg, 1)

    print(f"Saved slope map to {out_path}")


if __name__ == "__main__":
    elevation, meta, pixel_size = load_dem(max_size=1024)
    slope_deg = compute_slope(elevation, pixel_size)
    save_slope(slope_deg, meta)

    print("Slope min/max (deg):", np.nanmin(slope_deg), np.nanmax(slope_deg))