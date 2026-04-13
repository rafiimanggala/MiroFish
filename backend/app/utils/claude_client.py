"""
LLM client using claude CLI subprocess.
Replaces OpenAI SDK -- zero API keys needed.
"""

import subprocess
import json
import re
import logging
from typing import List, Dict, Optional, Any

logger = logging.getLogger('mirofish.claude')


class ClaudeClient:
    """LLM client wrapping `claude -p` CLI."""

    def __init__(self, model: Optional[str] = None):
        self.model = model  # optional override (sonnet, opus, haiku)

    def chat(
        self,
        messages: List[Dict[str, str]],
        temperature: float = 0.7,
        max_tokens: int = 4096,
        system_prompt: Optional[str] = None,
    ) -> str:
        """Send prompt to claude CLI, return text response."""
        full_prompt = self._build_prompt(messages, system_prompt)
        cmd = self._build_command(full_prompt)

        try:
            result = subprocess.run(
                cmd,
                capture_output=True,
                text=True,
                timeout=120,
            )
        except subprocess.TimeoutExpired:
            raise RuntimeError("Claude CLI timed out after 120s")

        if result.returncode != 0:
            logger.error("Claude CLI error: %s", result.stderr[:500])
            raise RuntimeError(f"Claude CLI failed: {result.stderr[:500]}")

        return result.stdout.strip()

    def chat_json(
        self,
        messages: List[Dict[str, str]],
        system_prompt: Optional[str] = None,
    ) -> Dict[str, Any]:
        """Get parsed JSON response from claude CLI."""
        augmented = self._append_json_instruction(messages)
        response = self.chat(augmented, system_prompt=system_prompt)
        cleaned = self._strip_code_blocks(response)

        try:
            return json.loads(cleaned)
        except json.JSONDecodeError as exc:
            raise ValueError(f"Invalid JSON from Claude: {cleaned[:300]}") from exc

    # -- internal helpers --

    def _build_prompt(
        self,
        messages: List[Dict[str, str]],
        system_prompt: Optional[str] = None,
    ) -> str:
        """Flatten message list into a single prompt string."""
        parts: list[str] = []
        if system_prompt:
            parts.append(f"[System]: {system_prompt}")

        for msg in messages:
            role = msg.get('role', 'user')
            content = msg.get('content', '')
            if role == 'system':
                parts.append(f"[System]: {content}")
            elif role == 'assistant':
                parts.append(f"[Assistant]: {content}")
            else:
                parts.append(content)

        return "\n\n".join(parts)

    def _build_command(self, prompt: str) -> List[str]:
        """Build the claude CLI command list."""
        cmd = ['claude', '-p', prompt, '--output-format', 'text']
        if self.model:
            cmd.extend(['--model', self.model])
        return cmd

    @staticmethod
    def _append_json_instruction(
        messages: List[Dict[str, str]],
    ) -> List[Dict[str, str]]:
        """Return new messages list with JSON instruction appended."""
        if not messages:
            return messages

        last = messages[-1]
        suffix = "\n\nRespond with valid JSON only. No markdown code blocks, no explanation."
        updated_last = {**last, 'content': last['content'] + suffix}
        return [*messages[:-1], updated_last]

    @staticmethod
    def _strip_code_blocks(text: str) -> str:
        """Remove markdown code block wrappers if present."""
        cleaned = re.sub(r'^```(?:json)?\s*\n?', '', text, flags=re.IGNORECASE)
        cleaned = re.sub(r'\n?```\s*$', '', cleaned)
        return cleaned.strip()
