import numpy as np
import rasterio
from rasterio.transform import from_origin

from explain.path_metrics import compute_path_metrics
from explain.generate_explanation import generate_contrastive_explanation


def create_test_raster(path, values):
    """Create a small temporary raster for testing."""

    height, width = values.shape

    transform = from_origin(0, height, 1, 1)

    with rasterio.open(
        path,
        "w",
        driver="GTiff",
        height=height,
        width=width,
        count=1,
        dtype="float32",
        transform=transform,
    ) as dst:
        dst.write(values.astype("float32"), 1)


def test_compute_path_metrics(tmp_path, monkeypatch):
    slope_file = tmp_path / "slope.tif"
    roughness_file = tmp_path / "roughness.tif"

    slope_values = np.ones((10, 10), dtype=np.float32) * 5
    roughness_values = np.ones((10, 10), dtype=np.float32) * 2

    create_test_raster(slope_file, slope_values)
    create_test_raster(roughness_file, roughness_values)

    import explain.path_metrics as path_metrics

    monkeypatch.setattr(
        path_metrics,
        "SLOPE_PATH",
        slope_file
    )

    monkeypatch.setattr(
        path_metrics,
        "ROUGHNESS_PATH",
        roughness_file
    )

    path = [(0, 0), (1, 0), (2, 0)]

    covariance = [
        [1.0, 0.0, 0.0],
        [0.0, 1.0, 0.0],
        [0.0, 0.0, 0.1],
    ]

    metrics = compute_path_metrics(path, covariance)

    assert metrics["slip_risk"] >= 0
    assert metrics["crater_covariance"] >= 0
    assert metrics["energy_proxy"] >= 0


def test_generate_contrastive_explanation(tmp_path, monkeypatch):
    slope_file = tmp_path / "slope.tif"
    roughness_file = tmp_path / "roughness.tif"

    slope_values = np.ones((10, 10), dtype=np.float32) * 5
    roughness_values = np.ones((10, 10), dtype=np.float32) * 2

    create_test_raster(slope_file, slope_values)
    create_test_raster(roughness_file, roughness_values)

    import explain.path_metrics as path_metrics

    monkeypatch.setattr(
        path_metrics,
        "SLOPE_PATH",
        slope_file
    )

    monkeypatch.setattr(
        path_metrics,
        "ROUGHNESS_PATH",
        roughness_file
    )

    path_a = [(0, 0), (1, 0), (2, 0)]
    path_b = [(0, 0), (1, 1), (2, 2)]

    covariance_a = np.eye(3).tolist()
    covariance_b = (np.eye(3) * 2).tolist()

    result = generate_contrastive_explanation(
        path_a,
        path_b,
        covariance_a,
        covariance_b,
    )

    assert result["chosen_path"] == "A"
    assert result["rejected_path"] == "B"
    assert "explanation" in result
    assert "Slip Risk" in result["explanation"]