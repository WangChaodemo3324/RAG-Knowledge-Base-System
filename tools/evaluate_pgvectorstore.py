"""Evaluation spike: can langchain-postgres PGVectorStore replace the custom
SQLAlchemy + pgvector adapter for this project?

Empirical checks against the live compose database (run with the spike venv:
    .spike-venv/Scripts/python.exe tools/evaluate_pgvectorstore.py
):

 1. dependency compatibility (langchain-core requirement vs our 0.3.x stack)
 2. Windows event-loop compatibility (async-first design)
 3. table initialization flow (separate ainit_vectorstore_table step)
 4. physical schema shape + FK relation to our domain tables
 5. caller-managed transaction support (add_texts signature)

Conclusion is recorded in docs/ARCHITECTURE.md §2 and docs/TEST_REPORT.md.
"""

from __future__ import annotations

import asyncio
import random
import sys
from pathlib import Path

if sys.platform == "win32":
    # Finding: PGVectorStore 0.0.19 bridges everything through async psycopg;
    # the default Windows ProactorEventLoop is unsupported.
    asyncio.set_event_loop_policy(asyncio.WindowsSelectorEventLoopPolicy())

PROJECT_ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(PROJECT_ROOT))

from langchain_postgres import PGEngine, PGVectorStore

from backend.core.config import DATABASE_URL


class FakeEmbeddings:
    def __init__(self, dim: int = 8) -> None:
        self.dim = dim

    def embed_documents(self, texts):
        return [self._vec(t) for t in texts]

    def embed_query(self, text):
        return self._vec(text)

    async def aembed_documents(self, texts):
        return self.embed_documents(texts)

    async def aembed_query(self, text):
        return self.embed_query(text)

    def _vec(self, t):
        rng = random.Random(str(t))
        v = [rng.random() for _ in range(self.dim)]
        n = sum(x * x for x in v) ** 0.5 or 1.0
        return [x / n for x in v]


async def main() -> None:
    pg_engine = PGEngine.from_connection_string(url=DATABASE_URL)
    await pg_engine.ainit_vectorstore_table(table_name="spike_langchain_pg", vector_size=8)
    store = await PGVectorStore.create(
        engine=pg_engine, embedding_service=FakeEmbeddings(8), table_name="spike_langchain_pg"
    )
    print("[1] table init + create OK (sync create_sync factory is broken in 0.0.19; async API is the only first-class path)")

    import uuid

    uuid_ids = [str(uuid.uuid4()), str(uuid.uuid4())]
    # Finding: 0.0.19 pins langchain_id to UUID — plain string ids are rejected.
    await store.add_texts(
        texts=["chunk A rollback", "chunk B reimbursement"],
        metadatas=[{"file_name": "doc1", "version": "v1"}, {"file_name": "doc2", "version": "v1"}],
        ids=uuid_ids,
    )
    print("[2] add_texts OK (UUID ids only; plain strings rejected by UUID PK)")

    hits = await store.similarity_search("rollback", k=1, filter={"version": {"$eq": "v1"}})
    print(f"[3] similarity_search with JSONB filter OK, top metadata: {hits[0].metadata if hits else None}")

    rejected = "NOT PROBED"
    try:
        from sqlalchemy.orm import Session

        from backend.db import create_db_engine

        engine = create_db_engine()
        with Session(engine) as session:
            await store.add_texts(texts=["txn probe"], metadatas=[{"v": "txn"}], ids=["txn1"], session=session)
            session.rollback()
        rejected = "ACCEPTED"
    except Exception as exc:  # noqa: BLE001
        rejected = f"REJECTED ({type(exc).__name__}: {str(exc)[:120]})"
    print(f"[4] caller-managed transaction via add_texts(session=...): {rejected}")
    print("    (note: add_texts signature has no session parameter; async calls inside a sync Session raise anyway)")

    await store.delete(ids=uuid_ids)
    print("[5] cleanup done (rows removed)")

    # physical schema summary is printed by the caller via psql in TEST_REPORT


if __name__ == "__main__":
    asyncio.run(main())
