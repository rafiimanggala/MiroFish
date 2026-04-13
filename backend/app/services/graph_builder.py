"""
Graph builder service -- local SQLite backend (no Zep).
Extracts entities and relationships from text chunks via ClaudeClient,
stores them in graph_nodes / graph_edges tables.
"""

import json
import uuid
import logging
from typing import Dict, Any, List, Optional, Callable

from ..utils.claude_client import ClaudeClient
from ..models.database import get_db

logger = logging.getLogger('mirofish')

EXTRACTION_SYSTEM_PROMPT = """You are a knowledge-graph extraction engine.
Given a text chunk and an ontology definition, extract entities and relationships.

IMPORTANT: Output valid JSON only. No markdown, no explanation.

## Output Schema

{
  "entities": [
    {
      "name": "Entity Name",
      "type": "EntityType (from ontology)",
      "attributes": {"attr_key": "attr_value"},
      "summary": "One-sentence description of this entity"
    }
  ],
  "relationships": [
    {
      "source": "Source Entity Name",
      "target": "Target Entity Name",
      "type": "RELATIONSHIP_TYPE (from ontology)",
      "fact": "One-sentence fact describing this relationship"
    }
  ]
}

## Rules
1. Only extract entities matching types defined in the ontology.
2. Use Person or Organization as fallback when no specific type fits.
3. Entity names should be canonical (full name, official title).
4. Merge references to the same entity under one canonical name.
5. Every relationship must reference entities that appear in the entities list.
"""


class GraphBuilderService:
    """Build knowledge graphs in local SQLite from text chunks."""

    def __init__(self):
        self.client = ClaudeClient()

    def create_graph(self, name: str) -> str:
        """Create a new graph entry and return its id."""
        graph_id = f"graph_{uuid.uuid4().hex[:12]}"
        logger.info("Created graph %s (%s)", graph_id, name)
        return graph_id

    def build_graph(
        self,
        graph_id: str,
        chunks: List[str],
        ontology: Dict[str, Any],
        progress_callback: Optional[Callable[[int], None]] = None,
    ) -> Dict[str, int]:
        """Extract entities/relationships from chunks and store in SQLite."""
        total = len(chunks)
        ontology_summary = self._summarize_ontology(ontology)

        for idx in range(0, total, 3):
            batch = chunks[idx: idx + 3]
            self._process_batch(graph_id, batch, ontology_summary)

            if progress_callback:
                pct = min(100, int(((idx + len(batch)) / total) * 100))
                progress_callback(pct)

        stats = self._count_graph(graph_id)
        logger.info("Graph %s built: %s", graph_id, stats)
        return stats

    def get_graph_data(self, graph_id: str) -> Dict[str, Any]:
        """Return all nodes and edges for a graph (D3-ready format)."""
        nodes = self._fetch_nodes(graph_id)
        edges = self._fetch_edges(graph_id)

        return {
            "graph_id": graph_id,
            "nodes": nodes,
            "edges": edges,
            "node_count": len(nodes),
            "edge_count": len(edges),
        }

    def delete_graph(self, graph_id: str) -> None:
        """Remove all nodes and edges for a graph."""
        conn = get_db()
        try:
            conn.execute("DELETE FROM graph_edges WHERE graph_id = ?", (graph_id,))
            conn.execute("DELETE FROM graph_nodes WHERE graph_id = ?", (graph_id,))
            conn.commit()
            logger.info("Deleted graph %s", graph_id)
        finally:
            conn.close()

    # -- internal helpers --

    def _summarize_ontology(self, ontology: Dict[str, Any]) -> str:
        """Compact ontology into a prompt-friendly string."""
        entity_lines = []
        for et in ontology.get("entity_types", []):
            attrs = ", ".join(a["name"] for a in et.get("attributes", []))
            entity_lines.append(f"- {et['name']}: {et.get('description', '')} [attrs: {attrs}]")

        edge_lines = []
        for ed in ontology.get("edge_types", []):
            pairs = ", ".join(
                f"{st['source']}->{st['target']}" for st in ed.get("source_targets", [])
            )
            edge_lines.append(f"- {ed['name']}: {ed.get('description', '')} [{pairs}]")

        return (
            "## Entity Types\n" + "\n".join(entity_lines) + "\n\n"
            "## Edge Types\n" + "\n".join(edge_lines)
        )

    def _process_batch(
        self,
        graph_id: str,
        batch: List[str],
        ontology_summary: str,
    ) -> None:
        """Send a batch of chunks to Claude and persist results."""
        combined_text = "\n\n---\n\n".join(batch)
        user_msg = (
            f"## Ontology\n\n{ontology_summary}\n\n"
            f"## Text to Extract From\n\n{combined_text}"
        )
        messages = [{"role": "user", "content": user_msg}]

        try:
            data = self.client.chat_json(
                messages=messages,
                system_prompt=EXTRACTION_SYSTEM_PROMPT,
            )
        except (RuntimeError, ValueError) as exc:
            logger.error("Extraction failed for batch: %s", exc)
            return

        entities = data.get("entities", [])
        relationships = data.get("relationships", [])

        self._upsert_entities(graph_id, entities)
        self._insert_edges(graph_id, relationships)

    def _upsert_entities(
        self, graph_id: str, entities: List[Dict]
    ) -> None:
        """Upsert entities into graph_nodes (merge by name+type)."""
        conn = get_db()
        try:
            for entity in entities:
                name = entity.get("name", "").strip()
                etype = entity.get("type", "Entity")
                if not name:
                    continue

                existing = conn.execute(
                    "SELECT id FROM graph_nodes WHERE graph_id = ? AND name = ? AND entity_type = ?",
                    (graph_id, name, etype),
                ).fetchone()

                attrs_json = json.dumps(entity.get("attributes", {}), ensure_ascii=False)
                summary = entity.get("summary", "")

                if existing:
                    conn.execute(
                        "UPDATE graph_nodes SET attributes_json = ?, summary = ? WHERE id = ?",
                        (attrs_json, summary, existing["id"]),
                    )
                else:
                    node_id = f"node_{uuid.uuid4().hex[:10]}"
                    conn.execute(
                        "INSERT INTO graph_nodes (id, graph_id, name, entity_type, attributes_json, summary) "
                        "VALUES (?, ?, ?, ?, ?, ?)",
                        (node_id, graph_id, name, etype, attrs_json, summary),
                    )
            conn.commit()
        finally:
            conn.close()

    def _insert_edges(
        self, graph_id: str, relationships: List[Dict]
    ) -> None:
        """Insert relationships into graph_edges."""
        conn = get_db()
        try:
            for rel in relationships:
                source = rel.get("source", "").strip()
                target = rel.get("target", "").strip()
                if not source or not target:
                    continue

                edge_id = f"edge_{uuid.uuid4().hex[:10]}"
                conn.execute(
                    "INSERT INTO graph_edges (id, graph_id, source_node_id, target_node_id, edge_type, fact) "
                    "VALUES (?, ?, ?, ?, ?, ?)",
                    (
                        edge_id,
                        graph_id,
                        source,
                        target,
                        rel.get("type", "RELATED_TO"),
                        rel.get("fact", ""),
                    ),
                )
            conn.commit()
        finally:
            conn.close()

    def _fetch_nodes(self, graph_id: str) -> List[Dict[str, Any]]:
        """Query all nodes for a graph."""
        conn = get_db()
        try:
            rows = conn.execute(
                "SELECT id, name, entity_type, attributes_json, summary "
                "FROM graph_nodes WHERE graph_id = ?",
                (graph_id,),
            ).fetchall()

            return [
                {
                    "id": row["id"],
                    "name": row["name"],
                    "type": row["entity_type"],
                    "attributes": json.loads(row["attributes_json"] or "{}"),
                    "summary": row["summary"] or "",
                }
                for row in rows
            ]
        finally:
            conn.close()

    def _fetch_edges(self, graph_id: str) -> List[Dict[str, Any]]:
        """Query all edges for a graph."""
        conn = get_db()
        try:
            rows = conn.execute(
                "SELECT id, source_node_id, target_node_id, edge_type, fact "
                "FROM graph_edges WHERE graph_id = ?",
                (graph_id,),
            ).fetchall()

            return [
                {
                    "id": row["id"],
                    "source": row["source_node_id"],
                    "target": row["target_node_id"],
                    "type": row["edge_type"],
                    "fact": row["fact"] or "",
                }
                for row in rows
            ]
        finally:
            conn.close()

    def _count_graph(self, graph_id: str) -> Dict[str, int]:
        """Return node and edge counts."""
        conn = get_db()
        try:
            nodes = conn.execute(
                "SELECT COUNT(*) as c FROM graph_nodes WHERE graph_id = ?",
                (graph_id,),
            ).fetchone()["c"]

            edges = conn.execute(
                "SELECT COUNT(*) as c FROM graph_edges WHERE graph_id = ?",
                (graph_id,),
            ).fetchone()["c"]

            return {"nodes_count": nodes, "edges_count": edges}
        finally:
            conn.close()
