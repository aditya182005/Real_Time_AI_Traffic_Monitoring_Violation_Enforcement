import cv2
from ultralytics import YOLO

model = YOLO("yolov8n.pt")

image = cv2.imread("data/images/test.jpg")

results = model(image)

annotated = results[0].plot()

cv2.imwrite("outputs/detections/result.jpg", annotated)

print("Detection completed.")