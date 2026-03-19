"""CypherGenerator: translates natural language questions into Neo4j Cypher queries
by invoking the nl-cypher skill via SkillsToolset, mirroring the eval subcommand pattern."""

from pathlib import Path
from sqlalchemy.orm import Session

from app.modules.utils.logger import setup_logger

logger = setup_logger(__name__)

_SKILLS_DIR = Path(__file__).parents[4] / ".kiro" / "skills"


class CypherGenerator:
    """Uses the nl-cypher skill (via SkillsToolset) to translate NL to Cypher."""

    def __init__(self, db: Session, user_id: str) -> None:
        from pydantic_ai import Agent
        from pydantic_ai_skills import SkillsToolset
        from pydantic_ai_skills.directory import SkillsDirectory
        from app.modules.intelligence.provider.provider_service import ProviderService

        model = ProviderService.create(db, user_id).get_pydantic_model()

        skills_dir = SkillsDirectory(path=str(_SKILLS_DIR))
        self._toolset = SkillsToolset(directories=[skills_dir])

        self._agent: Agent = Agent(
            model=model,
            instructions="You are a Neo4j Cypher expert. Use the nl-cypher skill.",
            toolsets=[self._toolset],
        )

        toolset = self._toolset

        @self._agent.instructions
        async def add_skill_instructions(ctx) -> str | None:
            return await toolset.get_instructions(ctx)

    async def generate(self, nl_query: str) -> str:
        """Translate *nl_query* into a Cypher query string using the nl-cypher skill."""
        logger.info("CypherGenerator: generating Cypher for query=%r", nl_query)

        prompt = (
            f"Use the nl-cypher skill to translate this question into a Neo4j Cypher query. "
            f"The nl-cypher skill has no scripts — load it and follow its instructions directly to produce the Cypher. "
            f"Do NOT call run_skill_script. Output only the Cypher query. "
            f"Question: {nl_query}"
        )
        result = await self._agent.run(prompt)
        raw: str = result.output.strip()

        # Extract only the first ```cypher (parameterized) block
        if "```" in raw:
            lines = raw.splitlines()
            in_block = False
            cypher_lines = []
            for line in lines:
                if line.strip().startswith("```") and not in_block:
                    in_block = True
                    continue
                if line.strip() == "```" and in_block:
                    break
                if in_block:
                    cypher_lines.append(line)
            raw = "\n".join(cypher_lines).strip()

        if "MATCH" not in raw.upper():
            raise ValueError(
                f"CypherGenerator: LLM did not produce a valid Cypher query. Got: {raw!r}"
            )
        if not raw.endswith(";"):
            raw += ";"

        logger.info("CypherGenerator: generated Cypher=%r", raw)
        return raw
