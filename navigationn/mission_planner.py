import math
import heapq

class MissionPlanner:
    def __init__(self, slope_map):
        # M5 will pass the numpy array / list of lists here. Zero I/O for you!
        self.slope_map = slope_map
        self.max_slope = 15.0 # Degrees
        self.rows = len(slope_map)
        self.cols = len(slope_map[0])

    def heuristic(self, a, b):
        """Euclidean distance straight-line heuristic for A*"""
        return math.dist(a, b)

    def get_step_cost(self, current, neighbor, uncertainty):
        """Calculates how 'expensive' it is to move to a neighboring tile."""
        nx, ny = neighbor
        slope = self.slope_map[ny][nx]

        # 1. Hard Constraint: Cannot pass steep slopes
        if slope > self.max_slope:
            return float('inf')

        # 2. Base Cost: Distance + slight penalty for slope
        cost = math.dist(current, neighbor) + (slope * 0.1)

        # 3. Dynamic Uncertainty Penalty (The PRD's Core Innovation)
        if uncertainty > 3.0:
            # CAUTION MODE: Slopes become extremely dangerous to cross
            cost += (slope * 1.5) 
            
        return cost

    def generate_xai_bullets(self, path, uncertainty):
        """Generates the 3-bullet explanation based on the chosen path."""
        # 1. Analyze the path we just took
        max_slope_on_path = 0
        for x, y in path:
            if self.slope_map[y][x] > max_slope_on_path:
                max_slope_on_path = self.slope_map[y][x]

        bullets = []

        # Bullet 1: Constraint
        bullets.append(f"1. CONSTRAINT: Max slope on path is {max_slope_on_path}°, safely under the {self.max_slope}° limit.")

        # Bullet 2: Hazard / Detour logic
        straight_line_dist = math.dist(path[0], path[-1])
        actual_dist = sum(math.dist(path[i], path[i+1]) for i in range(len(path)-1))
        
        if actual_dist > straight_line_dist * 1.2:
            bullets.append("2. HAZARD: Detour calculated to avoid steep crater rims.")
        else:
            bullets.append("2. HAZARD: Direct route taken through low-hazard terrain.")

        # Bullet 3: Uncertainty
        if uncertainty > 3.0:
            bullets.append(f"3. UNCERTAINTY: Position error high ({uncertainty}m) -> CAUTION MODE active. High-slope routes penalized.")
        else:
            bullets.append(f"3. UNCERTAINTY: Position error low ({uncertainty}m) -> Normal routing behavior.")

        return bullets

    def plan_route(self, start, goal, uncertainty):
        """A* Pathfinding algorithm."""
        # Priority queue for A*: stores tuples of (f_score, (x, y))
        open_set = []
        heapq.heappush(open_set, (0, start))
        
        came_from = {}
        
        # g_score: cheapest path from start to current node
        g_score = {start: 0}
        
        while open_set:
            _, current = heapq.heappop(open_set)

            # If we reached the goal, reconstruct the path
            if current == goal:
                path = []
                while current in came_from:
                    path.append(current)
                    current = came_from[current]
                path.append(start)
                
                # Reverse path so it goes from start -> goal
                final_path = path[::-1] 
                
                # Generate the explanations based on the final path
                reasons = self.generate_xai_bullets(final_path, uncertainty)
                
                return final_path, reasons

            cx, cy = current
            # Check 8 neighbors (horizontal, vertical, diagonal)
            neighbors = [(cx+1, cy), (cx-1, cy), (cx, cy+1), (cx, cy-1),
                         (cx+1, cy+1), (cx-1, cy-1), (cx+1, cy-1), (cx-1, cy+1)]

            for nx, ny in neighbors:
                # Ensure neighbor is inside the map bounds
                if 0 <= nx < self.cols and 0 <= ny < self.rows:
                    neighbor = (nx, ny)
                    
                    step_cost = self.get_step_cost(current, neighbor, uncertainty)
                    if step_cost == float('inf'):
                        continue # Skip unpassable terrain

                    tentative_g_score = g_score[current] + step_cost

                    if neighbor not in g_score or tentative_g_score < g_score[neighbor]:
                        came_from[neighbor] = current
                        g_score[neighbor] = tentative_g_score
                        f_score = tentative_g_score + self.heuristic(neighbor, goal)
                        heapq.heappush(open_set, (f_score, neighbor))

        # If loop finishes without returning, no path exists
        return [], ["FAILED: No safe path available under current constraints."]

# ==========================================
# TEST ZONE (Run this file to see it work!)
# ==========================================
if __name__ == "__main__":
    # Map where going straight is moderate (8 degrees), 
    # but going around is long and flat (1 degree).
    dummy_map = [
        [1, 1, 1, 1, 1, 1], # Long flat detour
        [1, 15, 15, 15, 1, 1],
        [1, 8, 8, 8, 1, 1], # Direct path (moderate slope)
        [1, 15, 15, 15, 1, 1],
        [1, 1, 1, 1, 1, 1],
        [1, 1, 1, 1, 1, 1]
    ]

    planner = MissionPlanner(dummy_map)
    start_pos = (0, 2) # Left side
    goal_pos = (5, 2)  # Right side

    print("--- RUN 1: CONFIDENT (Uncertainty = 1.2m) ---")
    path_confident, reasons_confident = planner.plan_route(start_pos, goal_pos, uncertainty=1.2)
    print(f"Path: {path_confident}")
    for r in reasons_confident:
        print(r)
    
    print("\n--- RUN 2: LOST / CAUTION MODE (Uncertainty = 4.5m) ---")
    path_lost, reasons_lost = planner.plan_route(start_pos, goal_pos, uncertainty=4.5)
    print(f"Path: {path_lost}")
    for r in reasons_lost:
        print(r)