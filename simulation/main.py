import sys
import os
import numpy as np

# This tells Python to look one folder up (in your main Code folder) for imports
sys.path.append(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

import time
from localization.localizer import Localizer
from navigation.mission_planner import MissionPlanner
from src.perception.detector import detect_craters

def start_orchestrator():
    print("🚀 SurakshaLander Orchestrator Started")
    
    # Initialize the real classes from your teammates
    localizer = Localizer()
    
    # TODO: Replace dummy_map with M1's real map variable once the .TIF is ready
    dummy_map = np.zeros((20, 20)) 
    planner = MissionPlanner(dummy_map)
    
    rover_running = True
    uncertainty = 0.0  
    
    # Starting coordinates
    current_pos = (0, 0)
    goal_pos = (10, 10)
    
    while rover_running:
        uncertainty += 0.8  
        print(f"\nRover at {current_pos} | Uncertainty: {uncertainty:.1f}m")
        
        if 3.0 < uncertainty <= 5.0:
            print("⚠️ CAUTION MODE: Hazard costs increased.")
            
        elif uncertainty > 5.0:
            print("🔄 RE-LOCALIZING TRIGGERED (> 5m)")
            
            # 1. M3 takes a picture and finds real craters
            #detected_craters = detect_craters(current_pos) 
            detected_craters = detect_craters(dummy_map)
            
            # 2. M2 uses M3's craters to fix the location
            current_pos, uncertainty = localizer.correct(detected_craters)
            
            print("   -> Recalculating route...")
            try:
                path, reasons = planner.plan_route(current_pos, goal_pos, uncertainty)
                print(f"   -> 📍 NEW PATH: {path}")
                print(f"   -> 📍 XAI: {reasons}")
            except Exception as e:
                print(f"   -> ❌ Planner failed: {e}")
                
        time.sleep(1.5)

if __name__ == "__main__":
    start_orchestrator()