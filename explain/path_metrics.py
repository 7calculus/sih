import math
from pathlib import Path

import numpy as np
import rasterio


# Terrain files produced by M1
SLOPE_PATH = Path(__file__).resolve().parent.parent / "data" / "processed" / "slope.tif"
ROUGHNESS_PATH = Path(__file__).resolve().parent.parent / "data" / "processed" / "roughness.tif"


def read_path_values(path, raster_path):
    """
    Read raster values at each (x, y) point in a path.
    """

    values = []

    with rasterio.open(raster_path) as src:
        for x, y in path:
            try:
                value = next(src.sample([(x, y)]))[0]

                if np.isfinite(value):
                    values.append(float(value))

            except Exception:
                continue

    return values


def compute_path_metrics(path, covariance):
    """
    Compute the three metrics required by M6:

    1. Slip risk
    2. Crater covariance exposure
    3. Energy proxy
    """

    if not path:
        return {
            "slip_risk": 0.0,
            "crater_covariance": 0.0,
            "energy_proxy": 0.0,
        }

    # --------------------------------------------------
    # Distance
    # --------------------------------------------------

    distance = 0.0

    for i in range(1, len(path)):
        x1, y1 = path[i - 1]
        x2, y2 = path[i]

        distance += math.hypot(x2 - x1, y2 - y1)

    # --------------------------------------------------
    # Read terrain information
    # --------------------------------------------------

    slope_values = read_path_values(path, SLOPE_PATH)
    roughness_values = read_path_values(path, ROUGHNESS_PATH)

    # --------------------------------------------------
    # Slip risk
    # --------------------------------------------------

    if slope_values:
        average_slope = sum(slope_values) / len(slope_values)
    else:
        average_slope = 0.0

    if roughness_values:
        average_roughness = sum(roughness_values) / len(roughness_values)
    else:
        average_roughness = 0.0

    slip_risk = average_slope + average_roughness

    # --------------------------------------------------
    # Crater covariance exposure
    # --------------------------------------------------

    covariance_array = np.asarray(covariance, dtype=float)

    if covariance_array.shape == (3, 3):
        crater_covariance = float(
            np.sqrt(
                covariance_array[0, 0]
                + covariance_array[1, 1]
            )
        )
    else:
        crater_covariance = 0.0

    # --------------------------------------------------
    # Energy proxy
    # --------------------------------------------------

    energy_proxy = distance * (1.0 + average_slope / 100.0)

    return {
        "slip_risk": float(slip_risk),
        "crater_covariance": crater_covariance,
        "energy_proxy": float(energy_proxy),
    }