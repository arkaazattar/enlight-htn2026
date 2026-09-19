"""Test downloaded model integrity without network access."""

from __future__ import annotations

import hashlib
import io
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

from face_app.models import ModelError, ModelSpec, download_models, verify_model


class ModelDownloadTests(unittest.TestCase):
    def test_download_verifies_hash_and_preserves_existing_file_on_failure(self) -> None:
        content = b"known model bytes"
        spec = ModelSpec("model.onnx", "https://example.invalid/model.onnx", hashlib.sha256(content).hexdigest(), len(content))
        with tempfile.TemporaryDirectory() as directory:
            model_dir = Path(directory)
            target = model_dir / spec.filename
            with patch("face_app.models.MODELS", (spec,)):
                with patch("face_app.models.urlopen", return_value=io.BytesIO(content)):
                    download_models(model_dir)
                self.assertTrue(verify_model(target, spec))

                target.write_bytes(b"old model")
                with patch("face_app.models.urlopen", return_value=io.BytesIO(b"wrong bytes")):
                    with self.assertRaisesRegex(ModelError, "SHA-256"):
                        download_models(model_dir)
                self.assertEqual(target.read_bytes(), b"old model")
                self.assertEqual(list(model_dir.glob(".download-*")), [])


if __name__ == "__main__":
    unittest.main()
