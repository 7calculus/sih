import rasterio
import numpy as np

for name in ["slope", "roughness"]:
    with rasterio.open(f"data/processed/{name}.tif") as src:
        arr = src.read(1)
        print(f"{name}.tif — shape: {arr.shape}, min: {np.nanmin(arr):.2f}, max: {np.nanmax(arr):.2f}, mean: {np.nanmean(arr):.2f}")