import matplotlib.pyplot as plt
import rasterio

fig, axes = plt.subplots(1, 2, figsize=(12, 6))

for ax, name in zip(axes, ["slope", "roughness"]):
    with rasterio.open(f"data/processed/{name}.tif") as src:
        # Downsample: read every 20th pixel instead of all 30,400x30,400
        arr = src.read(1, out_shape=(src.height // 20, src.width // 20))
        ax.imshow(arr, cmap="terrain")
        ax.set_title(name)

plt.tight_layout()
plt.savefig("terrain_check.png", dpi=150)
print("Saved to terrain_check.png")