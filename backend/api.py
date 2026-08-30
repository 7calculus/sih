from fastapi import FastAPI, WebSocket, WebSocketDisconnect
import asyncio
import json

app = FastAPI()

@app.get("/")
def read_root():
    return {"status": "SurakshaLander Backend is Live", "rover_mode": "Normal"}

# The new WebSocket endpoint
@app.websocket("/ws")
async def websocket_endpoint(websocket: WebSocket):
    await websocket.accept()
    print("🟢 Frontend Dashboard Connected!")
    
    try:
        while True:
            # For now, we simulate receiving live data from main.py
            dummy_telemetry = {
                "x": 5.2,
                "y": 12.4,
                "uncertainty": 2.1,
                "mode": "Driving"
            }
            
            # Send the JSON data through the open tunnel to the UI
            await websocket.send_text(json.dumps(dummy_telemetry))
            
            # Stream data every 1 second
            await asyncio.sleep(1)
            
    except WebSocketDisconnect:
        print("🔴 Frontend Dashboard Disconnected.")