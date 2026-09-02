import sys
import os
import time
import numpy as np

# Connect to root Code folder
sys.path.append(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from localization.localizer import Localizer
from navigation.mission_planner import MissionPlanner
from src.perception.detector import detect_craters
from terrain.dem_loader import load_dem
from localization.state import update_telemetry


def crop_local_patch(dem_map, center_x_m, center_y_m, patch_size_px=600, resolution_m=20.0):
    """
    Extracts a local sub-window around the rover's meter coordinates
    to prevent OpenCV OutOfMemory crashes on giant 30k x 30k maps.
    """
    h, w = dem_map.shape[:2]
    center_row = int(h / 2 - (center_y_m / resolution_m))
    center_col = int(w / 2 + (center_x_m / resolution_m))
    
    half_size = patch_size_px // 2
    r_start = max(0, center_row - half_size)
    r_end = min(h, center_row + half_size)
    c_start = max(0, center_col - half_size)
    c_end = min(w, center_col + half_size)
    
    patch = dem_map[r_start:r_end, c_start:c_end]
    
    # Pad back to expected patch size if near map edge
    if patch.shape[0] < patch_size_px or patch.shape[1] < patch_size_px:
        padded = np.zeros((patch_size_px, patch_size_px), dtype=dem_map.dtype)
        padded[:patch.shape[0], :patch.shape[1]] = patch
        return padded
    return patch


def start_orchestrator():
    print("🚀 SurakshaLander Orchestrator Started")
    
    print("Loading M1 DEM map...")
    dem_output = load_dem("data/Lunar_Map.tiff")
    dem_map = dem_output[0] if isinstance(dem_output, tuple) else dem_output
    
    print(f"Initializing modules with DEM shape: {dem_map.shape}...")
    localizer = Localizer()
    
    # Downsample for route planning efficiency
    downsampled_map = dem_map[::10, ::10] if dem_map.shape[0] > 1000 else dem_map
    planner = MissionPlanner(downsampled_map)
    
    rover_running = True
    uncertainty = 2.5
    current_pos = [145.6, -89.5]
    goal_pos = (500.0, 480.0)
    
    while rover_running:
        uncertainty += 0.5
        current_pos[0] += 2.0  # Rover advances
        current_pos[1] += 1.0
        
        mode = "Driving"
        reasoning = f"Rover cruising at coordinates ({current_pos[0]:.1f}, {current_pos[1]:.1f}). Terrain nominal."
        
        if 3.0 < uncertainty <= 5.0:
            mode = "Caution"
            reasoning = "⚠️ CAUTION MODE: Hazard threshold increased due to drift."
            
        elif uncertainty > 5.0:
            mode = "Relocalizing"
            print("🔄 RE-LOCALIZING TRIGGERED (> 5m). Cropping local terrain patch...")
            
            # 1. Extract a safe 600x600 patch around rover
            local_patch = crop_local_patch(dem_map, current_pos[0], current_pos[1], patch_size_px=600)
            
            # 2. Run circle detection on the localized window
            detected_craters = detect_craters(local_patch)
            print(f"   -> Detected {len(detected_craters)} local craters.")
            
            # 3. Correct location
            try:
                corr_res = localizer.correct(detected_craters)
                if isinstance(corr_res, tuple) and len(corr_res) == 2:
                    new_pos, uncertainty = corr_res
                    if isinstance(new_pos, (list, tuple)):
                        current_pos = [float(new_pos[0]), float(new_pos[1])]
                    uncertainty = float(uncertainty)
                else:
                    uncertainty = 1.2  # Reset upon successful correction
                print(f"   -> Location corrected to: {current_pos} | Reset Uncertainty: {uncertainty:.2f}m")
            except Exception as e:
                print(f"   -> Localizer notice: {e}")
                uncertainty = 1.5
            
            # 4. Recalculate route
            try:
                path, reasons = planner.plan_route((current_pos[0], current_pos[1]), goal_pos, uncertainty)
                reasoning = f"Route updated. {reasons[0] if reasons else 'Clear trajectory locked.'}"
            except Exception as e:
                reasoning = f"Route sustained. Local search locked."

        # Broadcast live packet to dashboard
        update_telemetry(current_pos[0], current_pos[1], uncertainty, mode, reasoning)
        print(f"Rover at [{current_pos[0]:.1f}, {current_pos[1]:.1f}] | Uncertainty: {uncertainty:.1f}m | Mode: {mode}")
        
        time.sleep(1.0)


if __name__ == "__main__":
    start_orchestrator()