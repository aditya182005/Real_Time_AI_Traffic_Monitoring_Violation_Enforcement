from app.video_processor import TrafficVideoProcessor


processor = TrafficVideoProcessor()

processor.process(
    "data/videos/traffic.mp4",
    "outputs/detections/tracked_traffic.mp4"
)

print("Video processing completed.")