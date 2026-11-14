"""Evaluation spike: can langchain-postgres PGVectorStore replace the custom
SQLAlchemy + pgvector adapter for this project?

Checks performed against the live compose database:
 1. schema ownership (its own table layout vs our domain schema)
 2. parent-child modeling (FK to our tables)
 3. transaction unification with our index_versions lifecycle
 4. version-scoped retrieval via metadata filter (shape of the query)
 5. engine/session ownership

The conclusion is recorded in ARCHITECTURE.md / PROGRESS.md.
"""

from __future__ import annotations

import random
import sys
from pathlib import Path

PROJECT_ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(PROJECT_ROOT))

from sqlalchemy import inspect, text

from backend.db import create_db_engine

COLLECTION = "spike_langchain_pg"


class FakeEmbeddings:
    """Deterministic embeddings; avoids loading the 2GB BGE-M3 model for a spike."""

    def __init__(self, dim: int = 8) -> None:
        self.dim = dim

    def embed_documents(self, texts):
        return [self._vec(t) for t in texts]

    def embed_query(self, text):
        return self._vec(text)

    def _vec(self, text):
        rng = random.Random(str(text))
        vector = [rng.random() for _ in range(self.dim)]
        norm = sum(v * v for v in vector) ** 0.5 or 1.0
        return [v / norm for v in vector]


def main() -> None:
    findings: list[str] = []
    engine = create_db_engine()

    # 1. Engine ownership: PGVectorStore accepts an external engine — but it
    #    internally creates its own sessionmaker and does not participate in
    #    caller-managed transactions.
    from langchain_postgres import PGVectorStore

    store = PGVectorStore.create_sync(
        engine=engine,
        collection_name=COLLECTION,
        embeddings=FakeEmbeddings(dim=8),
        pre_delete_collection=True,
        use_jsonb=True,
    )
    findings.append("create_sync(engine=...) accepted our engine; store owns its sessions internally")

    store.add_texts(
        texts=["child chunk A about rollback", "child chunk B about reimbursement"],
        metadatas=[{"file_name": "doc1", "version": "v1"}, {"file_name": "doc2", "version": "v1"}],
        ids=["c1", "c2"],
    )
    hits = store.similarity_search("rollback", k=1, filter={"version": {"$eq": "v1"}})
    findings.append(
        f"similarity_search with JSONB filter works; top hit metadata={hits[0].metadata if hits else None}"
    )

    # 2. Inspect its physical schema.
    inspector = inspect(engine)
    tables = [t for t in inspector.get_table_names() if "langchain" in t]
    columns = {t: [c["name"] for c in inspector.get_columns(t)] for t in tables}
    findings.append(f"PGVectorStore physical tables: {tables}")
    for t, cols in columns.items():
        findings.append(f"  {t}: {cols}")

    # 3. FK to our domain tables?
    fks = []
    for t in tables:
        fks.extend(inspector.get_foreign_keys(t))
    findings.append(f"FK constraints from PGVectorStore tables to our tables: {fks or 'NONE'}")

    # 4. Transaction unification: try writing a chunk and bumping our version row
    #    inside one user-controlled transaction using the store's API.
    unified_transaction_possible = False
    try:
        from sqlalchemy.orm import Session

        with Session(engine) as session:
            store.add_texts(texts=["txn probe"], metadatas=[{"v": "txn"}], ids=["txn1"], session=session)
            session.execute(text("SELECT 1"))
            session.rollback()  # probe only; nothing must persist
        unified_transaction_possible = True
    except TypeError as exc:
        findings.append(f"add_texts(session=...) rejected: {exc}")
    except Exception as exc:  # noqa: BLE001
        findings.append(f"shared-session attempt failed: {type(exc).__name__}: {exc}")
    findings.append(f"single caller-managed transaction across store + domain tables: {unified_transaction_possible}")

    # cleanup
    with engine.begin() as conn:
        conn.execute(
            text(
                "DELETE FROM langchain_pg_collection WHERE name = :n"
                if any("collection" in t for t in tables)
                else "SELECT 1"
            ),
            {"n": COLLECTION},
        )
        for t in tables:
            if "embedding" in t:
                conn.execute(text(f"DELETE FROM {t} WHERE collection_id IN (SELECT uuid FROM langchain_pg_collection)"))
                conn.execute(text(f"DELETE FROM {t} WHERE id = 'txn1'"))

    print("== PGVectorStore evaluation findings ==")
    for line in findings:
        print(f"- {line}")


if __name__ == "__main__":
    main()
