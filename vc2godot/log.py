import logging
from pathlib import Path


def setup_logging(out_dir: Path):
    out_dir.mkdir(parents=True, exist_ok=True)
    log = logging.getLogger("vc2godot")
    log.setLevel(logging.INFO)
    log.handlers.clear()
    fmt = logging.Formatter("%(asctime)s [%(levelname)s] %(message)s")
    sh = logging.StreamHandler()
    sh.setFormatter(fmt)
    fh = logging.FileHandler(out_dir / "import.log", encoding="utf-8")
    fh.setFormatter(fmt)
    log.addHandler(sh)
    log.addHandler(fh)
    return log
