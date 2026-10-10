from ultralytics import YOLO


model = YOLO("models/emergency_vehicle.pt")

results = model("data/images/test.jpg")

results[0].save(
    filename="outputs/detections/emergency_test.jpg"
)

print("Emergency vehicle detection completed.")