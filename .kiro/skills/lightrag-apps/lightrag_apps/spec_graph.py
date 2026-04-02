#!/usr/bin/env python3
"""
LightRAG Wiki Generator - Index code repositories and query with natural language

Usage:
    # First time: Create .venv (required)
    uv sync --directory /path/to/lightrag-apps

    # Index repository
    uv run --directory /path/to/lightrag-apps spec-graph index --repo /path/to/repo

    # Query the indexed graph
    uv run --directory /path/to/lightrag-apps spec-graph query -s ./spec_graph_storage "Tell me about X"

Features:
- Uses LightRAG for knowledge graph construction
- Supports GitHub Copilot and OpenAI models
- Supports hybrid, global, and local query modes
"""

import argparse
import asyncio
import os
import sys
import subprocess
from pathlib import Path
from typing import Optional, Set, Tuple
from dataclasses import dataclass, field

try:
    from dotenv import load_dotenv
    load_dotenv()
except ImportError:
    pass

# Configuration
@dataclass
class Config:
    """LightRAG configuration"""

    # Paths
    repo_path: Path = Path(".")  # Current directory by default
    working_dir: Path = Path("./spec_graph_storage")
    workspace: str = ""
    verbose: bool = False

    # Repository metadata (auto-detected from git if available)
    repo_name: Optional[str] = None  # Auto-detected from git or directory name

    # LLM settings - Use GitHub Copilot by default
    llm_model_name: str = "github_copilot/gpt-4o"
    embedding_model_name: str = "github_copilot/text-embedding-3-small"
    api_key: str = "oauth2"  # For GitHub Copilot

    # Indexing settings
    code_extensions: Set[str] = field(default_factory=lambda: {
        '.py', '.md', '.txt'
    })
    min_file_size: int = 50
    batch_report_interval: int = 10

    # Parallel processing settings (optimized for GitHub Copilot Business)
    max_parallel_insert: int = 48
    llm_model_max_async: int = 96
    embedding_func_max_async: int = 48

    @classmethod
    def from_env(cls, **overrides) -> "Config":
        """Create config from environment variables"""
        config_dict = {}

        if repo := os.getenv("REPO_PATH"):
            config_dict["repo_path"] = Path(repo)

        if working_dir := os.getenv("WORKING_DIR"):
            config_dict["working_dir"] = Path(working_dir)

        if workspace := os.getenv("WORKSPACE"):
            config_dict["workspace"] = workspace

        if repo_name := os.getenv("REPO_NAME"):
            config_dict["repo_name"] = repo_name

        if llm_model := os.getenv("LLM_MODEL"):
            config_dict["llm_model_name"] = llm_model

        if embed_model := os.getenv("EMBEDDING_MODEL"):
            config_dict["embedding_model_name"] = embed_model

        if api_key := os.getenv("API_KEY"):
            config_dict["api_key"] = api_key

        if min_size := os.getenv("MIN_FILE_SIZE"):
            config_dict["min_file_size"] = int(min_size)

        if batch := os.getenv("BATCH_REPORT_INTERVAL"):
            config_dict["batch_report_interval"] = int(batch)

        # Parallel processing settings
        if max_parallel := os.getenv("MAX_PARALLEL_INSERT"):
            config_dict["max_parallel_insert"] = int(max_parallel)

        if llm_async := os.getenv("LLM_MODEL_MAX_ASYNC"):
            config_dict["llm_model_max_async"] = int(llm_async)

        if embed_async := os.getenv("EMBEDDING_FUNC_MAX_ASYNC"):
            config_dict["embedding_func_max_async"] = int(embed_async)

        # Apply overrides
        config_dict.update(overrides)

        return cls(**config_dict)

    def validate(self, require_working_dir: bool = False):
        """Validate configuration"""
        if not self.repo_path.exists():
            raise ValueError(f"Repository path does not exist: {self.repo_path}")

        if require_working_dir and not self.working_dir.exists():
            raise ValueError(f"Working directory does not exist: {self.working_dir}")

        # Auto-detect repo name if not set
        if self.repo_name is None:
            self.repo_name = self._detect_repo_name()

        self.working_dir.mkdir(parents=True, exist_ok=True)

    def _detect_repo_name(self) -> str:
        """Auto-detect repository name from git or directory name"""
        # Try to get from git remote
        try:
            result = subprocess.run(
                ["git", "remote", "get-url", "origin"],
                cwd=self.repo_path,
                capture_output=True,
                text=True,
                timeout=5
            )
            if result.returncode == 0:
                url = result.stdout.strip()
                # Extract repo name from URL
                name = url.rstrip('/').split('/')[-1]
                if name.endswith('.git'):
                    name = name[:-4]
                return name
        except Exception:
            pass

        # Fallback to directory name
        return self.repo_path.resolve().name


# Repository Indexer
class RepositoryIndexer:
    """Index repository into LightRAG knowledge graph"""

    def __init__(self, config: Config):
        self.config = config
        self.rag = None

    async def index_repository(self) -> Tuple[int, int, int]:
        """Index all files in repository"""
        import os
        from lightrag import LightRAG
        from lightrag.llm.llama_index_impl import (
            llama_index_complete_if_cache,
            llama_index_embed,
        )
        from lightrag.utils import EmbeddingFunc
        from llama_index.llms.litellm import LiteLLM
        from llama_index.embeddings.litellm import LiteLLMEmbedding

        # Set API key in environment
        os.environ["OPENAI_API_KEY"] = self.config.api_key

        print(f"\n📚 Indexing repository: {self.config.repo_name}")
        print(f"   Path: {self.config.repo_path}")
        print(f"   Working directory: {self.config.working_dir}")
        print(f"   LLM: {self.config.llm_model_name}")
        print(f"   Embedding: {self.config.embedding_model_name}")

        # Initialize LightRAG
        working_dir = self.config.working_dir

        async def llm_model_func(
            prompt, system_prompt=None, history_messages=[], **kwargs
        ) -> str:
            if "llm_instance" not in kwargs:
                kwargs["llm_instance"] = LiteLLM(
                    model=self.config.llm_model_name,
                    api_key=self.config.api_key,
                    temperature=0.7,
                )
            return await llama_index_complete_if_cache(
                kwargs["llm_instance"], prompt, system_prompt, history_messages
            )

        async def embedding_func(texts: list[str]):
            embed_model = LiteLLMEmbedding(
                model_name=self.config.embedding_model_name,
                api_key=self.config.api_key,
            )
            return await llama_index_embed(texts, embed_model=embed_model)

        self.rag = LightRAG(
            working_dir=working_dir,
            workspace=self.config.workspace,
            llm_model_func=llm_model_func,
            embedding_func=EmbeddingFunc(
                embedding_dim=1536,
                max_token_size=8192,
                func=embedding_func
            ),
            llm_model_name=self.config.llm_model_name,
            max_parallel_insert=self.config.max_parallel_insert,
            llm_model_max_async=self.config.llm_model_max_async,
            embedding_func_max_async=self.config.embedding_func_max_async
        )
        await self.rag.initialize_storages()

        # Find all files
        files_to_index = []
        for ext in self.config.code_extensions:
            files_to_index.extend(self.config.repo_path.rglob(f"*{ext}"))

        # Filter by size and sort
        files_to_index = [
            f for f in files_to_index
            if f.is_file() and f.stat().st_size >= self.config.min_file_size
        ]
        files_to_index.sort()

        print(f"\n📁 Found {len(files_to_index)} files to index")

        # Index files
        indexed = 0
        skipped = 0
        errors = 0

        for i, file_path in enumerate(files_to_index, 1):
            try:
                # Read file
                content = file_path.read_text(encoding='utf-8', errors='ignore')

                if not content.strip():
                    skipped += 1
                    continue

                # Prepare document
                rel_path = file_path.relative_to(self.config.repo_path)
                doc = f"# File: {rel_path}\n\n{content}"

                # Insert into knowledge graph
                await self.rag.ainsert(doc)
                indexed += 1

                # Progress report
                if i % self.config.batch_report_interval == 0:
                    print(f"   Progress: {i}/{len(files_to_index)} files processed")

            except Exception as e:
                print(f"   ⚠️  Error indexing {file_path}: {e}")
                errors += 1

        print(f"\n✅ Indexing complete!")
        print(f"   Indexed: {indexed} files")
        print(f"   Skipped: {skipped} files (empty)")
        print(f"   Errors: {errors} files")

        return indexed, skipped, errors


# CLI Functions
async def run_index(config: Config):
    """Run the indexing step"""
    print("\n" + "=" * 80)
    print("STEP 1: INDEXING REPOSITORY")
    print("=" * 80)

    indexer = RepositoryIndexer(config)
    indexed, skipped, errors = await indexer.index_repository()

    return indexed > 0


async def run_query(config: Config, query: str, mode: str = "hybrid"):
    """Run a custom query against the knowledge graph"""
    print("\n" + "=" * 80)
    print("CUSTOM QUERY MODE")
    print("=" * 80)
    print(f"Spec graph directory: {config.working_dir}")
    print(f"Query: {query}")
    print(f"Mode: {mode}")


    from lightrag import LightRAG, QueryParam
    from lightrag.utils import EmbeddingFunc
    from llama_index.llms.litellm import LiteLLM
    from llama_index.embeddings.litellm import LiteLLMEmbedding
    from lightrag.llm.llama_index_impl import (
            llama_index_complete_if_cache,
            llama_index_embed,
        )

    if config.verbose:
        from lightrag.utils import setup_logger
        setup_logger("lightrag", level="DEBUG")

    async def llm_model_func(
            prompt, system_prompt=None, history_messages=[], **kwargs
        ) -> str:
            if "llm_instance" not in kwargs:
                kwargs["llm_instance"] = LiteLLM(
                    model=config.llm_model_name,
                    api_key=config.api_key,
                    temperature=0.7,
                )
            return await llama_index_complete_if_cache(
                kwargs["llm_instance"], prompt, system_prompt, history_messages
            )

    async def embedding_func(texts: list[str]):
            embed_model = LiteLLMEmbedding(
                model_name=config.embedding_model_name,
                api_key=config.api_key,
            )
            return await llama_index_embed(texts, embed_model=embed_model)

    # Initialize LightRAG


    rag = LightRAG(working_dir=config.working_dir,
                   workspace=config.workspace,
                   llm_model_func=llm_model_func,
                   llm_model_name=config.llm_model_name,
                   embedding_func=EmbeddingFunc(
                    embedding_dim=1536,
                    max_token_size=8192,
                    func=embedding_func
                    )
                   )
    await rag.initialize_storages()


    result = await rag.aquery(query, param=QueryParam(mode=mode))

    print("\n" + "=" * 80)
    print("QUERY RESULT")
    print("=" * 80)
    print(result)


def test_setup(config: Optional[Config] = None):
    """Test the setup"""
    if config is None:
        config = Config.from_env()

    # Validate config to trigger auto-detection
    try:
        config.validate(False)
    except Exception as e:
        pass

    print("=" * 80)
    print("TESTING SETUP")
    print("=" * 80)

    errors = []
    warnings = []

    # Check repository
    if config.repo_path.exists():
        print(f"✅ Repository found: {config.repo_path}")
        print(f"   Repository name: {config.repo_name}")

        py_files = list(config.repo_path.glob("**/*.py"))
        md_files = list(config.repo_path.glob("**/*.md"))
        print(f"   - Python files: {len(py_files)}")
        print(f"   - Markdown files: {len(md_files)}")
    else:
        errors.append(f"❌ Repository not found: {config.repo_path}")

    # Check Python version
    py_version = sys.version_info
    if py_version >= (3, 8):
        print(f"✅ Python version: {py_version.major}.{py_version.minor}.{py_version.micro}")
    else:
        errors.append(f"❌ Python 3.8+ required, found {py_version.major}.{py_version.minor}")

    # Try importing LightRAG
    try:
        import lightrag
        print("✅ LightRAG module can be imported")
    except ImportError as e:
        errors.append(f"❌ Cannot import LightRAG: {e}")
        warnings.append("⚠️  Install: uv pip install lightrag-hku")

    # Check write permissions
    try:
        config.working_dir.mkdir(exist_ok=True)
        test_file = config.working_dir / "test.txt"
        test_file.write_text("test")
        test_file.unlink()
        print("✅ Write permissions OK")
    except Exception as e:
        errors.append(f"❌ Write permission error: {e}")

    print("\n" + "=" * 80)
    if errors:
        print("ERRORS FOUND:")
        for error in errors:
            print(error)

    if warnings:
        print("\nWARNINGS:")
        for warning in warnings:
            print(warning)

    if not errors and not warnings:
        print("✅ ALL CHECKS PASSED - Ready to generate wiki!")
    elif not errors:
        print("⚠️  READY (with warnings)")
    else:
        print("❌ SETUP INCOMPLETE - Fix errors before proceeding")

    print("=" * 80)

    return len(errors) == 0


def main():
    """Main CLI entry point"""
    parser = argparse.ArgumentParser(
        description="Generate hierarchical wiki from code repository using LightRAG"
    )

    subparsers = parser.add_subparsers(dest="command", help="Command to run")

    def add_spec_graph_arg(p):
        p.add_argument(
            "--working-dir", "-s",
            dest="working_dir",
            type=Path,
            help="Path to the LightRAG spec graph directory (indexed data)"
        )

    # Index command
    index_parser = subparsers.add_parser("index", help="Index repository")
    index_parser.add_argument(
        "--repo",
        type=Path,
        help="Path to repository (default: current directory)"
    )
    add_spec_graph_arg(index_parser)

    # Query command
    query_parser = subparsers.add_parser("query", help="Run a custom query against the knowledge graph")
    query_parser.add_argument(
        "query",
        type=str,
        help="Query string to run against the knowledge graph"
    )
    query_parser.add_argument(
        "--mode", "-m",
        type=str,
        choices=["local", "global", "hybrid"],
        default="hybrid",
        help="Query mode (default: hybrid)"
    )
    add_spec_graph_arg(query_parser)
    query_parser.add_argument(
        '--verbose', '-v',
        action='store_true',
        help="Enable verbose output"
    )

    # Test command
    test_parser = subparsers.add_parser("test", help="Test setup")
    test_parser.add_argument(
        "--repo",
        type=Path,
        help="Path to repository (default: current directory)"
    )
    add_spec_graph_arg(test_parser)

    args = parser.parse_args()

    # Build config from args
    config_kwargs = {}
    if hasattr(args, 'repo') and args.repo:
        config_kwargs['repo_path'] = args.repo
    if hasattr(args, 'working_dir') and args.working_dir:
        config_kwargs['working_dir'] = args.working_dir
    if hasattr(args, 'verbose') and args.verbose:
        config_kwargs['verbose'] = True
    if hasattr(args, 'model') and args.model:
        config_kwargs['llm_model_name'] = args.model

    config = Config.from_env(**config_kwargs)

    try:
        config.validate(args.command == "query")
    except Exception as e:
        print(f"❌ Configuration error: {e}")
        sys.exit(1)

    # Run command
    if args.command == "index":
        asyncio.run(run_index(config))
    elif args.command == "query":
        asyncio.run(run_query(config, args.query, args.mode))
    elif args.command == "test":
        success = test_setup(config)
        sys.exit(0 if success else 1)
    else:
        parser.print_help()
        sys.exit(1)


if __name__ == "__main__":
    main()
