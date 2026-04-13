"""
Ontology generator service.
Analyzes documents and simulation requirements to produce
entity types and relationship types for knowledge graph construction.
"""

import logging
from typing import Dict, Any, List, Optional

from ..utils.claude_client import ClaudeClient

logger = logging.getLogger('mirofish')

ONTOLOGY_SYSTEM_PROMPT = """You are an expert knowledge-graph ontology designer.
Analyze the provided documents and simulation requirement, then design entity types
and relationship types suitable for a social-media opinion simulation.

IMPORTANT: Output valid JSON only. No markdown, no explanation.

## Output Schema

{
  "entity_types": [
    {
      "name": "PascalCaseTypeName",
      "description": "Short description (max 100 chars)",
      "attributes": [
        {"name": "snake_case_attr", "type": "text", "description": "..."}
      ],
      "examples": ["Example Entity 1", "Example Entity 2"]
    }
  ],
  "edge_types": [
    {
      "name": "UPPER_SNAKE_CASE",
      "description": "Short description (max 100 chars)",
      "source_targets": [{"source": "SourceType", "target": "TargetType"}]
    }
  ],
  "analysis_summary": "Brief analysis of the documents."
}

## Design Rules

1. Generate ~10 entity types. Last 2 MUST be Person and Organization (fallback types).
2. Generate 6-10 edge types covering realistic social-media interactions.
3. Entity types must represent real-world actors that can post/interact on social media
   (people, companies, government agencies, media outlets, etc.).
4. Do NOT create abstract concepts, topics, or attitudes as entity types.
5. Each entity type: 1-3 attributes. Avoid reserved names: name, uuid, group_id, created_at, summary.
6. Attribute names in snake_case, entity names in PascalCase, edge names in UPPER_SNAKE_CASE.
"""

MAX_TEXT_LENGTH = 50000


class OntologyGenerator:
    """Analyze documents and produce ontology for graph construction."""

    def __init__(self):
        self.client = ClaudeClient()

    def generate(
        self,
        document_texts: List[str],
        simulation_requirement: str,
        additional_context: Optional[str] = None,
    ) -> Dict[str, Any]:
        """Generate ontology from documents and simulation requirement."""
        user_message = self._build_prompt(
            document_texts, simulation_requirement, additional_context
        )
        messages = [{"role": "user", "content": user_message}]

        result = self.client.chat_json(
            messages=messages,
            system_prompt=ONTOLOGY_SYSTEM_PROMPT,
        )

        return self._validate(result)

    def _build_prompt(
        self,
        document_texts: List[str],
        requirement: str,
        context: Optional[str],
    ) -> str:
        """Build user prompt from documents and requirement."""
        combined = "\n\n---\n\n".join(document_texts)
        original_len = len(combined)

        if len(combined) > MAX_TEXT_LENGTH:
            combined = combined[:MAX_TEXT_LENGTH]
            combined += f"\n\n...(truncated from {original_len} chars)..."

        prompt = (
            f"## Simulation Requirement\n\n{requirement}\n\n"
            f"## Document Content\n\n{combined}"
        )

        if context:
            prompt += f"\n\n## Additional Context\n\n{context}"

        return prompt

    def _validate(self, result: Dict[str, Any]) -> Dict[str, Any]:
        """Validate and fix ontology output, ensuring fallback types."""
        validated = {
            "entity_types": list(result.get("entity_types", [])),
            "edge_types": list(result.get("edge_types", [])),
            "analysis_summary": result.get("analysis_summary", ""),
        }

        validated["entity_types"] = self._ensure_entity_fields(
            validated["entity_types"]
        )
        validated["edge_types"] = self._ensure_edge_fields(
            validated["edge_types"]
        )
        validated["entity_types"] = self._ensure_fallback_types(
            validated["entity_types"]
        )

        return validated

    def _ensure_entity_fields(
        self, entities: List[Dict]
    ) -> List[Dict]:
        """Ensure every entity has required fields; truncate descriptions."""
        cleaned = []
        seen_names: set = set()

        for entity in entities:
            name = entity.get("name", "Unknown")
            if name in seen_names:
                logger.warning("Duplicate entity type '%s' removed", name)
                continue
            seen_names.add(name)

            desc = entity.get("description", f"A {name} entity.")
            if len(desc) > 100:
                desc = desc[:97] + "..."

            cleaned.append({
                "name": name,
                "description": desc,
                "attributes": entity.get("attributes", []),
                "examples": entity.get("examples", []),
            })

        return cleaned[:10]

    def _ensure_edge_fields(self, edges: List[Dict]) -> List[Dict]:
        """Ensure every edge has required fields."""
        cleaned = []
        for edge in edges:
            desc = edge.get("description", "")
            if len(desc) > 100:
                desc = desc[:97] + "..."

            cleaned.append({
                "name": edge.get("name", "RELATED_TO").upper(),
                "description": desc,
                "source_targets": edge.get("source_targets", []),
            })

        return cleaned[:10]

    def _ensure_fallback_types(
        self, entities: List[Dict]
    ) -> List[Dict]:
        """Guarantee Person and Organization fallback types exist."""
        names = {e["name"] for e in entities}

        fallbacks = []
        if "Person" not in names:
            fallbacks.append({
                "name": "Person",
                "description": "Any individual not fitting other specific person types.",
                "attributes": [
                    {"name": "full_name", "type": "text", "description": "Full name"},
                    {"name": "role", "type": "text", "description": "Role or occupation"},
                ],
                "examples": ["ordinary citizen", "anonymous netizen"],
            })
        if "Organization" not in names:
            fallbacks.append({
                "name": "Organization",
                "description": "Any organization not fitting other specific types.",
                "attributes": [
                    {"name": "org_name", "type": "text", "description": "Organization name"},
                    {"name": "org_type", "type": "text", "description": "Type of organization"},
                ],
                "examples": ["small business", "community group"],
            })

        if not fallbacks:
            return entities

        # Make room if needed (max 10)
        slots_needed = len(fallbacks)
        max_specific = 10 - slots_needed
        trimmed = entities[:max_specific]
        return [*trimmed, *fallbacks]
