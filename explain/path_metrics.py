import math
from pathlib import Path

import numpy as np
import rasterio


# Terrain files produced by M1
SLOPE_PATH = (
    Path(__file__).resolve().parent.parent
    / "data"
    / "processed"
    / "slope.tif"
)

ROUGHNESS_PATH = (
    Path(__file__).resolve().parent.parent
    / "data"
    / "processed"
    / "roughness.tif"
)


def read_path_values(path, raster_path):
    """
    Read raster values at each (x, y) point in a path.

    This function only reads terrain data.
    It does not modify the raster files.
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


def _extract_covariance_matrix(pose):
    """
    Extract the covariance matrix from an M2 pose payload.

    Supported inputs:

    1. M2 get_pose() output:
       (x, y, heading, covariance)

    2. A dictionary containing:
       {"covariance": [...]}

    3. A covariance matrix directly.
    """

    if pose is None:
        return None

    # Case 1: dictionary payload
    if isinstance(pose, dict):
        pose = pose.get("covariance")

        if pose is None:
            return None

    # Case 2: M2 get_pose() tuple/list
    #
    # M2 returns:
    # (x, y, heading, covariance)
    #
    if isinstance(pose, (tuple, list)):
        if len(pose) == 4:
            pose = pose[3]

    try:
        covariance_array = np.asarray(pose, dtype=float)
    except (TypeError, ValueError):
        return None

    return covariance_array


def compute_path_metrics(path, pose):
    """
    Compute the three quantitative metrics required by M6:

    1. Slip risk
       = average slope + average roughness

    2. Crater covariance exposure
       = sqrt(covariance[0,0] + covariance[1,1])

    3. Energy proxy
       = path distance * slope penalty

    Parameters
    ----------
    path : list
        List of (x, y) path coordinates.

    pose : tuple, list, dict, or covariance matrix
        Current localization pose supplied by M5.
        M2's official get_pose() format is:

            (x, y, heading, covariance)
    """

    # --------------------------------------------------
    # Empty path
    # --------------------------------------------------

    if not path:
        return {
            "slip_risk": 0.0,
            "crater_covariance": 0.0,
            "energy_proxy": 0.0,
        }

    # --------------------------------------------------
    # Calculate path distance
    # --------------------------------------------------

    distance = 0.0

    for i in range(1, len(path)):
        x1, y1 = path[i - 1]
        x2, y2 = path[i]

        distance += math.hypot(
            x2 - x1,
            y2 - y1,
        )

    # --------------------------------------------------
    # Read terrain information
    # --------------------------------------------------

    slope_values = read_path_values(
        path,
        SLOPE_PATH,
    )

    roughness_values = read_path_values(
        path,
        ROUGHNESS_PATH,
    )

    # --------------------------------------------------
    # Average slope
    # --------------------------------------------------

    if slope_values:
        average_slope = (
            sum(slope_values)
            / len(slope_values)
        )
    else:
        average_slope = 0.0

    # --------------------------------------------------
    # Average roughness
    # --------------------------------------------------

    if roughness_values:
        average_roughness = (
            sum(roughness_values)
            / len(roughness_values)
        )
    else:
        average_roughness = 0.0

    # --------------------------------------------------
    # Slip Risk
    #
    # Higher slope + roughness = higher risk
    # --------------------------------------------------

    slip_risk = (
        average_slope
        + average_roughness
    )

    # --------------------------------------------------
    # Crater Covariance Exposure
    # --------------------------------------------------

    covariance_array = _extract_covariance_matrix(
        pose
    )

    if (
        covariance_array is not None
        and covariance_array.shape == (3, 3)
    ):
        crater_covariance = float(
            np.sqrt(
                covariance_array[0, 0]
                + covariance_array[1, 1]
            )
        )
    else:
        crater_covariance = 0.0

    # --------------------------------------------------
    # Energy Proxy
    #
    # Longer path + steeper terrain = higher energy
    # --------------------------------------------------

    energy_proxy = (
        distance
        * (1.0 + average_slope / 100.0)
    )

    # --------------------------------------------------
    # Return M6 metrics
    # --------------------------------------------------

    return {
        "slip_risk": float(slip_risk),
        "crater_covariance": float(
            crater_covariance
        ),
        "energy_proxy": float(energy_proxy),
    }