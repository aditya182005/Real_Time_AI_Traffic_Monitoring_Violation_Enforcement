
import ultralytics

model = ultralytics.YOLO("yolov8n.pt")

model.train(
    data="data/emergency_vehicle/data.yaml",
    epochs=10,
    imgsz=640,
    batch=8,
    name="emergency_vehicle"
)

print("Training completed.")