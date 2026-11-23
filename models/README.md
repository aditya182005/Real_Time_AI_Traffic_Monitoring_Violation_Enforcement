# Models

| File | Used for | How to get it |
|---|---|---|
| `emergency_vehicle.pt` | Ambulance, fire truck, police car detection | **Included in the repository** (about 6 MB). Trained with `notebooks/train_emergency_colab.ipynb`; measured results are in [docs/EVALUATION.md](../docs/EVALUATION.md). Replace it with your own after fine-tuning on your cameras ([docs/TRAINING.md](../docs/TRAINING.md)). |
| `helmet.pt` | Motorcycle riders without a helmet (optional) | Not included: train your own ([docs/TRAINING.md](../docs/TRAINING.md#helmet-model)). |

The general vehicle model `yolov8n.pt` is downloaded automatically by
Ultralytics on first use (and is baked into the Docker image).

`emergency_vehicle.pt` is the one exception to the `*.pt` rule in `.gitignore`.
Its first 12 characters of SHA-256 are stored with every violation record as
the model version, so a changed model shows in the evidence.

Ultralytics YOLOv8 is licensed AGPL-3.0; read its terms before turning this
into a product or a service.
