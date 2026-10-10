
from app.violation.database import save_violation

save_violation(
    track_id=101,
    signal_state="RED",
    evidence_path="outputs/violations/test.jpg"
)

print("Test violation record inserted.")

