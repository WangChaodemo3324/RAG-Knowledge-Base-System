from __future__ import annotations

from pathlib import Path
from typing import Iterable

import numpy as np
import onnxruntime as ort
from huggingface_hub import snapshot_download
from langchain_core.embeddings import Embeddings
from transformers import AutoTokenizer


class BgeM3OnnxEmbeddings(Embeddings):
    """BAAI/bge-m3 ONNX embedding adapter.

    The bge-m3 repository ships PyTorch weights as ``pytorch_model.bin``. With
    torch < 2.6, recent transformers versions refuse to load that format, so
    this adapter reads the official ONNX export and uses its sentence_embedding
    output directly.
    """

    def __init__(
        self,
        model_name: str = "BAAI/bge-m3",
        batch_size: int = 8,
        max_length: int = 8192,
        normalize_embeddings: bool = True,
    ) -> None:
        self.model_name = model_name
        self.batch_size = batch_size
        self.max_length = max_length
        self.normalize_embeddings = normalize_embeddings
        self.model_dir = self._resolve_model_dir(model_name)
        self.onnx_dir = self.model_dir / "onnx"
        self.tokenizer = AutoTokenizer.from_pretrained(str(self.onnx_dir))
        self.session = ort.InferenceSession(
            str(self.onnx_dir / "model.onnx"),
            providers=["CPUExecutionProvider"],
        )
        self.input_names = {item.name for item in self.session.get_inputs()}

    def embed_documents(self, texts: list[str]) -> list[list[float]]:
        return self._embed(texts)

    def embed_query(self, text: str) -> list[float]:
        return self._embed([text])[0]

    def _embed(self, texts: list[str]) -> list[list[float]]:
        vectors: list[list[float]] = []
        for batch in self._batches(texts):
            encoded = self.tokenizer(
                batch,
                padding=True,
                truncation=True,
                max_length=self.max_length,
                return_tensors="np",
            )
            inputs = {
                name: value.astype(np.int64)
                for name, value in encoded.items()
                if name in self.input_names
            }
            output = self.session.run(["sentence_embedding"], inputs)[0]
            if self.normalize_embeddings:
                output = self._normalize(output)
            vectors.extend(output.astype(np.float32).tolist())
        return vectors

    def _batches(self, texts: list[str]) -> Iterable[list[str]]:
        for start in range(0, len(texts), self.batch_size):
            yield texts[start : start + self.batch_size]

    def _normalize(self, values: np.ndarray) -> np.ndarray:
        norm = np.linalg.norm(values, axis=1, keepdims=True)
        norm = np.maximum(norm, 1e-12)
        return values / norm

    def _resolve_model_dir(self, model_name: str) -> Path:
        allow_patterns = [
            "onnx/config.json",
            "onnx/model.onnx",
            "onnx/model.onnx_data",
            "onnx/sentencepiece.bpe.model",
            "onnx/special_tokens_map.json",
            "onnx/tokenizer.json",
            "onnx/tokenizer_config.json",
        ]
        try:
            return Path(
                snapshot_download(
                    repo_id=model_name,
                    allow_patterns=allow_patterns,
                    local_files_only=True,
                )
            )
        except Exception:
            return Path(snapshot_download(repo_id=model_name, allow_patterns=allow_patterns))
