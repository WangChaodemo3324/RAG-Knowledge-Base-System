from __future__ import annotations

import re
from dataclasses import dataclass
from typing import Any

from langchain_core.documents import Document
from langchain_text_splitters import RecursiveCharacterTextSplitter

from backend.core.config import (
    CHILD_CHUNKING_MODE,
    CHUNK_OVERLAP,
    CHUNK_SEPARATORS,
    CHUNK_SIZE,
    CHUNKING_STRATEGY,
    PARENT_CHUNK_OVERLAP,
    PARENT_CHUNK_SIZE,
    SEMANTIC_MIN_CHUNK_SIZE,
)


@dataclass
class ParentChildChunks:
    parents: list[Any]
    children: list[Any]


class SemanticBoundaryChildSplitter:
    """Splits child chunks on topic-friendly boundaries, with recursive fallback."""

    def __init__(
        self,
        chunk_size: int = CHUNK_SIZE,
        chunk_overlap: int = CHUNK_OVERLAP,
        min_chunk_size: int = SEMANTIC_MIN_CHUNK_SIZE,
        separators: list[str] | None = None,
    ) -> None:
        if chunk_overlap >= chunk_size:
            raise ValueError("chunk_overlap must be smaller than chunk_size")
        self.chunk_size = chunk_size
        self.chunk_overlap = chunk_overlap
        self.min_chunk_size = min_chunk_size
        self.separators = separators or CHUNK_SEPARATORS
        self.fallback_splitter = RecursiveCharacterTextSplitter(
            chunk_size=self.chunk_size,
            chunk_overlap=self.chunk_overlap,
            separators=self.separators,
        )

    def create_documents(self, texts: list[str], metadatas: list[dict[str, Any]]) -> list[Any]:
        documents: list[Any] = []
        for text, metadata in zip(texts, metadatas):
            for chunk in self.split_text(text):
                documents.append(Document(page_content=chunk, metadata=dict(metadata)))
        return documents

    def split_text(self, text: str) -> list[str]:
        units = self._semantic_units(text)
        if not units:
            return []

        chunks: list[str] = []
        current: list[str] = []

        for unit in units:
            if self._is_section_boundary(unit) and current:
                self._flush(current, chunks)
                current = []

            if len(unit) > self.chunk_size:
                self._flush(current, chunks)
                current = []
                chunks.extend(self.fallback_splitter.split_text(unit))
                continue

            candidate = self._join(current + [unit])
            if current and len(candidate) > self.chunk_size:
                previous = self._flush(current, chunks)
                overlap_seed = self._semantic_tail(previous)
                current = [overlap_seed] if overlap_seed else []
                candidate = self._join(current + [unit])
                if len(candidate) > self.chunk_size:
                    current = []

            current.append(unit)

        self._flush(current, chunks)
        return self._merge_tiny_chunks(chunks)

    def _semantic_units(self, text: str) -> list[str]:
        blocks = [block.strip() for block in re.split(r"\n\s*\n", text) if block.strip()]
        units: list[str] = []
        for block in blocks:
            if len(block) <= self.chunk_size:
                units.append(block)
                continue

            lines = [line.strip() for line in block.splitlines() if line.strip()]
            if len(lines) > 1:
                units.extend(lines)
                continue

            sentences = re.split(r"(?<=[。！？!?；;])\s*", block)
            units.extend(sentence.strip() for sentence in sentences if sentence.strip())
        return units

    def _merge_tiny_chunks(self, chunks: list[str]) -> list[str]:
        if not chunks:
            return []
        merged: list[str] = []
        for chunk in chunks:
            if not merged:
                merged.append(chunk)
                continue
            candidate = self._join([merged[-1], chunk])
            if len(merged[-1]) < self.min_chunk_size and len(candidate) <= self.chunk_size:
                merged[-1] = candidate
            else:
                merged.append(chunk)
        return merged

    def _semantic_tail(self, text: str) -> str:
        if self.chunk_overlap <= 0:
            return ""
        tail = text[-self.chunk_overlap :].strip()
        boundary_positions = [tail.rfind(mark) for mark in ("\n", "。", "！", "？", "；", ";")]
        boundary = max(boundary_positions)
        if boundary > 0 and len(tail) - boundary >= max(40, self.chunk_overlap // 3):
            return tail[boundary + 1 :].strip()
        return tail

    def _is_section_boundary(self, text: str) -> bool:
        stripped = text.lstrip()
        return stripped.startswith("#") or bool(re.match(r"^(第[一二三四五六七八九十0-9]+[章节条]|[0-9]+[.、])", stripped))

    def _flush(self, current: list[str], chunks: list[str]) -> str:
        text = self._join(current)
        if text:
            chunks.append(text)
        current.clear()
        return text

    def _join(self, parts: list[str]) -> str:
        return "\n\n".join(part for part in parts if part).strip()


class OverlapChunker:
    """Splits documents with recursive separators and overlapping context."""

    def __init__(
        self,
        chunk_size: int = CHUNK_SIZE,
        chunk_overlap: int = CHUNK_OVERLAP,
        separators: list[str] | None = None,
        strategy: str = CHUNKING_STRATEGY,
    ) -> None:
        if chunk_overlap >= chunk_size:
            raise ValueError("chunk_overlap must be smaller than chunk_size")
        self.chunk_size = chunk_size
        self.chunk_overlap = chunk_overlap
        self.separators = separators or CHUNK_SEPARATORS
        self.strategy = strategy
        self.splitter = RecursiveCharacterTextSplitter(
            chunk_size=self.chunk_size,
            chunk_overlap=self.chunk_overlap,
            separators=self.separators,
        )

    def split(self, documents: list[Any]) -> list[Any]:
        return self.splitter.create_documents(
            [doc.page_content for doc in documents],
            metadatas=[doc.metadata for doc in documents],
        )

    def settings(self) -> dict[str, Any]:
        return {
            "chunking_strategy": self.strategy,
            "chunk_size": self.chunk_size,
            "chunk_overlap": self.chunk_overlap,
            "chunk_separators": "|".join(self.separators),
        }


class ParentChildChunker:
    """Creates large parent chunks and smaller overlapping child chunks."""

    def __init__(
        self,
        parent_chunk_size: int = PARENT_CHUNK_SIZE,
        parent_chunk_overlap: int = PARENT_CHUNK_OVERLAP,
        child_chunk_size: int = CHUNK_SIZE,
        child_chunk_overlap: int = CHUNK_OVERLAP,
        child_chunking_mode: str = CHILD_CHUNKING_MODE,
        semantic_min_chunk_size: int = SEMANTIC_MIN_CHUNK_SIZE,
        separators: list[str] | None = None,
        strategy: str = CHUNKING_STRATEGY,
    ) -> None:
        if parent_chunk_overlap >= parent_chunk_size:
            raise ValueError("parent_chunk_overlap must be smaller than parent_chunk_size")
        if child_chunk_overlap >= child_chunk_size:
            raise ValueError("child_chunk_overlap must be smaller than child_chunk_size")
        if child_chunk_size > parent_chunk_size:
            raise ValueError("child_chunk_size must not be larger than parent_chunk_size")

        self.parent_chunk_size = parent_chunk_size
        self.parent_chunk_overlap = parent_chunk_overlap
        self.child_chunk_size = child_chunk_size
        self.child_chunk_overlap = child_chunk_overlap
        self.child_chunking_mode = child_chunking_mode
        self.semantic_min_chunk_size = semantic_min_chunk_size
        self.separators = separators or CHUNK_SEPARATORS
        self.strategy = strategy
        self.parent_splitter = RecursiveCharacterTextSplitter(
            chunk_size=self.parent_chunk_size,
            chunk_overlap=self.parent_chunk_overlap,
            separators=self.separators,
        )
        if self.child_chunking_mode == "semantic_boundary":
            self.child_splitter = SemanticBoundaryChildSplitter(
                chunk_size=self.child_chunk_size,
                chunk_overlap=self.child_chunk_overlap,
                min_chunk_size=self.semantic_min_chunk_size,
                separators=self.separators,
            )
        else:
            self.child_splitter = RecursiveCharacterTextSplitter(
                chunk_size=self.child_chunk_size,
                chunk_overlap=self.child_chunk_overlap,
                separators=self.separators,
            )

    def split(self, documents: list[Any]) -> ParentChildChunks:
        parents: list[Any] = []
        children: list[Any] = []

        for document_index, document in enumerate(documents):
            metadata = dict(getattr(document, "metadata", {}) or {})
            metadata["document_index"] = document_index
            parent_docs = self.parent_splitter.create_documents([document.page_content], metadatas=[metadata])
            for parent_index_in_document, parent in enumerate(parent_docs):
                parent_index = len(parents)
                parent.metadata = dict(getattr(parent, "metadata", {}) or {})
                parent.metadata.update(
                    {
                        "parent_index": parent_index,
                        "parent_index_in_document": parent_index_in_document,
                    }
                )
                parents.append(parent)

                child_docs = self.child_splitter.create_documents([parent.page_content], metadatas=[parent.metadata])
                for child_index_in_parent, child in enumerate(child_docs):
                    child.metadata = dict(getattr(child, "metadata", {}) or {})
                    child.metadata.update(
                        {
                            "parent_index": parent_index,
                            "child_index_in_parent": child_index_in_parent,
                        }
                    )
                    children.append(child)

        return ParentChildChunks(parents=parents, children=children)

    def settings(self) -> dict[str, Any]:
        return {
            "chunking_strategy": self.strategy,
            "parent_chunk_size": self.parent_chunk_size,
            "parent_chunk_overlap": self.parent_chunk_overlap,
            "child_chunk_size": self.child_chunk_size,
            "child_chunk_overlap": self.child_chunk_overlap,
            "child_chunking_mode": self.child_chunking_mode,
            "semantic_min_chunk_size": self.semantic_min_chunk_size,
            "chunk_size": self.child_chunk_size,
            "chunk_overlap": self.child_chunk_overlap,
            "chunk_separators": "|".join(self.separators),
        }
