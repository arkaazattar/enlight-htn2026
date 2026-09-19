"""Download and verify the OpenCV Zoo models used by the camera app."""

from __future__ import annotations

import hashlib
import os
from dataclasses import dataclass
from pathlib import Path
from tempfile import NamedTemporaryFile
from urllib.error import URLError
from urllib.request import Request, urlopen


class ModelError(Exception):
    """A model is missing, damaged, or could not be downloaded."""


@dataclass(frozen=True)
class ModelSpec:
    filename: str
    url: str
    sha256: str
    size: int


# Hashes and sizes are the published OpenCV Zoo Git LFS object values.
YUNET = ModelSpec(
    filename="face_detection_yunet_2023mar.onnx",
    url="https://github.com/opencv/opencv_zoo/raw/main/models/face_detection_yunet/face_detection_yunet_2023mar.onnx",
    sha256="8f2383e4dd3cfbb4553ea8718107fc0423210dc964f9f4280604804ed2552fa4",
    size=232589,
)
SFACE = ModelSpec(
    filename="face_recognition_sface_2021dec.onnx",
    url="https://github.com/opencv/opencv_zoo/raw/main/models/face_recognition_sface/face_recognition_sface_2021dec.onnx",
    sha256="0ba9fbfa01b5270c96627c4ef784da859931e02f04419c829e83484087c34e79",
    size=38696353,
)
MODELS = (YUNET, SFACE)


def model_paths(model_dir: Path) -> tuple[Path, Path]:
    return model_dir / YUNET.filename, model_dir / SFACE.filename


def verify_model(path: Path, spec: ModelSpec) -> bool:
    if not path.is_file() or path.stat().st_size != spec.size:
        return False
    digest = hashlib.sha256()
    with path.open("rb") as source:
        for chunk in iter(lambda: source.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest() == spec.sha256


def require_models(model_dir: Path) -> tuple[Path, Path]:
    paths = model_paths(model_dir)
    for path, spec in zip(paths, MODELS):
        if not verify_model(path, spec):
            raise ModelError(
                f"Missing or damaged model: {path}. Run 'python -m face_app download-models'."
            )
    return paths


def download_models(model_dir: Path) -> None:
    model_dir.mkdir(parents=True, exist_ok=True)
    for spec in MODELS:
        destination = model_dir / spec.filename
        if verify_model(destination, spec):
            print(f"Already verified: {destination}")
            continue

        print(f"Downloading {spec.filename} ({spec.size / 1_000_000:.1f} MB)...", flush=True)
        temporary: Path | None = None
        try:
            request = Request(spec.url, headers={"User-Agent": "htn2026-face-app/1.0"})
            with urlopen(request, timeout=60) as response:
                with NamedTemporaryFile(dir=model_dir, prefix=".download-", delete=False) as output:
                    temporary = Path(output.name)
                    total = 0
                    while chunk := response.read(1024 * 1024):
                        total += len(chunk)
                        if total > spec.size:
                            raise ModelError(f"Downloaded model is larger than expected: {spec.filename}")
                        output.write(chunk)
            if not verify_model(temporary, spec):
                raise ModelError(
                    f"Downloaded model failed its size or SHA-256 check: {spec.filename}"
                )
            os.replace(temporary, destination)
            print(f"Verified: {destination}")
        except (OSError, URLError) as exc:
            raise ModelError(f"Could not download {spec.filename}: {exc}") from exc
        finally:
            if temporary is not None:
                temporary.unlink(missing_ok=True)
