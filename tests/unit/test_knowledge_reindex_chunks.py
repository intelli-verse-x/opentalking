"""Reindex retires only the selected document's old extraction artifact."""

from __future__ import annotations

import asyncio

from opentalking.agent.knowledge_store import KnowledgeStore


class _InertIndex:
    def index_document(self, **kwargs):
        pass


def test_reindex_clears_selected_document_chunks_preserves_unrelated_document(tmp_path):
    async def scenario():
        source = tmp_path / "synthetic.txt"
        source.write_text("synthetic local text for reindex", encoding="utf-8")
        store = KnowledgeStore(
            db_path=tmp_path / "knowledge.sqlite3",
            knowledge_root=tmp_path / "knowledge",
            knowledge_index=_InertIndex(),
        )
        first = await store.add_document(
            kb_id="synthetic",
            filename="first.txt",
            mime_type="text/plain",
            source_path=source,
        )
        second = await store.add_document(
            kb_id="synthetic",
            filename="second.txt",
            mime_type="text/plain",
            source_path=source,
        )
        with store._connect() as conn:
            assert (
                conn.execute(
                    "SELECT COUNT(*) FROM knowledge_chunks WHERE doc_id = ?", (first.id,)
                ).fetchone()[0]
                > 0
            )
        requested = await store.request_reindex(kb_id="synthetic", doc_id=first.id)
        assert requested.status == "uploaded" and requested.generation == first.generation + 1
        with store._connect() as conn:
            assert (
                conn.execute(
                    "SELECT COUNT(*) FROM knowledge_chunks WHERE doc_id = ?", (first.id,)
                ).fetchone()[0]
                == 0
            )
            assert (
                conn.execute(
                    "SELECT COUNT(*) FROM knowledge_chunks WHERE doc_id = ?", (second.id,)
                ).fetchone()[0]
                > 0
            )

    asyncio.run(scenario())
