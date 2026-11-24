"""Train the helmet model and install it at models/helmet.pt.

    python scripts/train_helmet.py --epochs 40 --device 0

Dataset: YOLO format in ``data/helmet/`` (``data.yaml`` plus ``images/`` and
``labels/`` for train and val, optionally test). Download one from a public
source such as Roboflow Universe (check its licence). Its classes must make
helmet / no-helmet clear, for example ``helmet`` and ``no_helmet``, or
``head`` (counted as no helmet) and ``helmet``.

It reuses the emergency trainer, so the options (``--epochs``, ``--device``,
``--time``, ``--report`` ...) are the same. It adds two things: a check that
the classes can be understood, and a reminder that a model scored on its own
dataset says nothing about your camera. Always run your own footage through
``scripts/benchmark.py`` before trusting it.
"""

import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))
sys.path.insert(0, str(ROOT / "scripts"))

import train_emergency  # noqa: E402

DATA_YAML = ROOT / "data" / "helmet" / "data.yaml"
INSTALLED = ROOT / "models" / "helmet.pt"


def class_names(data_yaml):
    """Class names from a data.yaml (list or index mapping), no YAML library."""

    names, inside = [], False

    for raw in Path(data_yaml).read_text(encoding="utf-8").splitlines():
        line = raw.strip()

        if line.startswith("names:"):
            rest = line[len("names:"):].strip()

            if rest.startswith("["):
                return [n.strip().strip("'\"") for n in
                        rest.strip("[]").split(",") if n.strip()]

            inside = True
            continue

        if inside:
            if line.startswith("-"):
                names.append(line[1:].strip().strip("'\""))
            elif ":" in line and raw.startswith((" ", "\t")):
                names.append(line.split(":", 1)[1].strip().strip("'\""))
            elif line and not line.startswith("#"):
                break

    return names


def check_classes(data_yaml):
    """Raise ValueError unless the classes cover helmet and no-helmet."""

    from app.detection.helmet_detector import normalise
    from app.violation.helmet import HELMET, NO_HELMET

    kinds = {normalise(n) for n in class_names(data_yaml)}

    if not {HELMET, NO_HELMET} <= kinds:
        raise ValueError(
            f"{data_yaml}: the classes must include both a helmet class and "
            f"a no-helmet (or head) class; found {class_names(data_yaml)}.")


def main(argv=None, **hooks):
    argv = list(argv if argv is not None else sys.argv[1:])

    if "--data" not in argv:
        argv += ["--data", str(DATA_YAML)]

    data = argv[argv.index("--data") + 1]

    try:
        check_classes(data)
    except (OSError, ValueError) as exc:
        print(f"Cannot start: {exc}", file=sys.stderr)
        return 1

    for flag, value in (("--output", str(INSTALLED)), ("--name", "helmet")):
        if flag not in argv:
            argv += [flag, value]

    code = train_emergency.main(argv, **hooks)

    if code == 0:
        print("\nNext: measure it on YOUR footage before relying on it:\n"
              "  python scripts/benchmark.py --clips clips --truth "
              "clips/truth.csv -- --helmet")

    return code


if __name__ == "__main__":
    sys.exit(main())
