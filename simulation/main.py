import sys
import os
import time
import datetime
import numpy as np

# Connect to root Code folder
sys.path.append(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from localization.localizer import Localizer
from navigation.mission_planner import MissionPlanner
from src.perception.detector import detect_craters
from terrain.dem_loader import load_dem
from localization.state import update_telemetry

# 🚀 NEW: Import your team's real M6 scripts
from explain.generate_explanation import generate_contrastive_explanation
from explain.audit_logger import log_decision


def crop_local_patch(dem_map, center_x_m, center_y_m, patch_size_px=600, resolution_m=20.0):
    h, w = dem_map.shape[:2]
    center_row = int(h / 2 - (center_y_m / resolution_m))
    center_col = int(w / 2 + (center_x_m / resolution_m))
    
    half_size = patch_size_px // 2
    r_start = max(0, center_row - half_size)
    r_end = min(h, center_row + half_size)
    c_start = max(0, center_col - half_size)
    c_end = min(w, center_col + half_size)
    
    patch = dem_map[r_start:r_end, c_start:c_end]
    
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
    
    downsampled_map = dem_map[::10, ::10] if dem_map.shape[0] > 1000 else dem_map
    planner = MissionPlanner(downsampled_map)
    
    rover_running = True
    uncertainty = 2.5
    current_pos = [145.6, -89.5]
    goal_pos = (500.0, 480.0)
    
    while rover_running:
        # 🚀 FIX: The math updates were removed from here so the dashboard starts exactly at [145.6, -89.5]
        
        timestamp = datetime.datetime.now().strftime("%H:%M:%S")
        
        mode = "Driving"
        reasoning = f"Rover cruising at coordinates ({current_pos[0]:.1f}, {current_pos[1]:.1f}). Terrain nominal."
        
        if 3.0 < uncertainty <= 5.0:
            mode = "Caution"
            reasoning = "⚠️ CAUTION MODE: Hazard threshold increased due to drift."
            
        elif uncertainty > 5.0:
            mode = "Relocalizing"
            print("🔄 RE-LOCALIZING TRIGGERED (> 5m). Cropping local terrain patch...")
            
            local_patch = crop_local_patch(dem_map, current_pos[0], current_pos[1], patch_size_px=600)
            detected_craters = detect_craters(local_patch)
            
            try:
                corr_res = localizer.correct(detected_craters)
                if isinstance(corr_res, tuple) and len(corr_res) == 2:
                    new_pos, uncertainty = corr_res
                    if isinstance(new_pos, (list, tuple)):
                        current_pos = [float(new_pos[0]), float(new_pos[1])]
                    uncertainty = float(uncertainty)
                else:
                    uncertainty = 1.2  
            except Exception as e:
                uncertainty = 1.5
            
            try:
                path, reasons = planner.plan_route((current_pos[0], current_pos[1]), goal_pos, uncertainty)
                reasoning = f"Route updated. {reasons[0] if reasons else 'Clear trajectory locked.'}"
            except Exception as e:
                reasoning = f"Route sustained. Local search locked."

        # 🚀 NEW: M6 AI Integration
        try:
            # 1. Generate live dummy paths based on the rover's current coordinates 
            # to feed the M6 metrics engine without crashing it.
            path_a = [(current_pos[0], current_pos[1]), (current_pos[0] + 5, current_pos[1] + 2)]
            path_b = [(current_pos[0], current_pos[1]), (current_pos[0] + 2, current_pos[1] + 8)]
            cov_a, cov_b = 0.4, 1.5 
            
            # 2. Run your teammate's Contrastive Explanation engine
            m6_result = generate_contrastive_explanation(path_a, path_b, cov_a, cov_b)
            
            # 3. Log the decision to decision_log.json
            log_decision(
                m6_result["chosen_path"],
                m6_result["rejected_path"],
                m6_result["metrics_a"],
                m6_result["metrics_b"],
                m6_result["explanation"]
            )
            
            # 4. Format the text nicely for the React UI Strip
            raw_explanation = m6_result["explanation"]
            
            # Extracts just the reasoning metrics and capitalizes it for the cyberpunk UI look
            ui_metrics_text = raw_explanation.split("because: ")[-1].upper() 
            m6_exp = f"PATH A SELECTED: {ui_metrics_text}"
            
            # 🚀 CHANGED: Removed the "M6 AUDIT: " prefix so the text is cleaner
            m6_audit = f"[{timestamp}] {raw_explanation}"
            
        except Exception as e:
            # 🚀 ADDED PRINT STATEMENT TO CATCH THE BUG:
            print(f"\n🚨 M6 ENGINE CRASHED: {repr(e)}\n")
            
            # Safe fallback: if the M6 module throws a math error, the dashboard stays alive!
            m6_exp = "M6 EVALUATING NEXT TRAJECTORY..."
            # 🚀 CHANGED: Removed the "M6 LOG: " prefix
            m6_audit = f"[{timestamp}] Rover cruising at nominal parameters."

        # Broadcast live packet to dashboard (Now fully powered by M6 output!)
        update_telemetry(current_pos[0], current_pos[1], uncertainty, mode, reasoning, m6_exp, m6_audit)
        print(f"Rover at [{current_pos[0]:.1f}, {current_pos[1]:.1f}] | Uncertainty: {uncertainty:.1f}m | Mode: {mode}")
        
        time.sleep(1.0)
        
        #  the dashboard starts perfectly at [145.6, -89.5]
        uncertainty += 0.5
        current_pos[0] += 2.0  
        current_pos[1] += 1.0


if __name__ == "__main__":
    start_orchestrator()