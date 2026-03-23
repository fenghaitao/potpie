#!/usr/bin/env python3
"""
Potpie CLI - Complete command-line interface for code intelligence

Combines both graph construction and agent interactions in a single tool.
"""
import asyncio
import json
import sys
import subprocess
import threading
from collections.abc import Callable
from pathlib import Path
from typing import Any, Optional

# Load .env file before importing potpie
from dotenv import load_dotenv
load_dotenv(override=True)

import click
from rich.console import Console
from rich.markdown import Markdown
from rich.panel import Panel
from rich.progress import Progress, SpinnerColumn, TextColumn
from rich.table import Table

from potpie import PotpieRuntime
from potpie.agents.context import ChatContext
from potpie.types import ProjectStatus

console = Console()


def _verbose_skill_stream_callback() -> Callable[[str], None]:
    """Line writer for StreamingLocalSkillScriptExecutor (subprocess reader threads).

    Avoids Rich and the asyncio loop: Rich Console is not thread-safe, and
    marshaling with call_soon_threadsafe can stall if the loop does not get
    enough turns while a tool is blocked in asyncio.to_thread.
    """
    lock = threading.Lock()

    def write_line(line: str) -> None:
        with lock:
            sys.stdout.write(line + "\n")
            sys.stdout.flush()

    return write_line


# ============================================================================
# STREAMING EXECUTOR
# ============================================================================

from pydantic_ai_skills.local import LocalSkillScriptExecutor  # noqa: E402
from pydantic_ai_skills.exceptions import SkillScriptExecutionError  # noqa: E402


class StreamingLocalSkillScriptExecutor(LocalSkillScriptExecutor):
    """Subclass of LocalSkillScriptExecutor that streams output line-by-line via a callback."""

    def __init__(
        self,
        callback: Callable[[str], None],
        python_executable: str | Path | None = None,
        timeout: int = 30,
    ) -> None:
        super().__init__(python_executable=python_executable, timeout=timeout)
        self._callback = callback

    async def run(self, script, args: dict[str, Any] | None = None) -> Any:
        if script.uri is None:
            raise SkillScriptExecutionError(f"Script '{script.name}' has no URI for subprocess execution")

        script_path = Path(script.uri)
        cmd = [self._python_executable, "-u", str(script_path)]

        if args:
            for key, value in args.items():
                if isinstance(value, bool):
                    if value:
                        cmd.append(f'--{key}')
                elif isinstance(value, list):
                    for item in value:
                        cmd.append(f'--{key}')
                        cmd.append(str(item))
                elif value is not None:
                    cmd.append(f'--{key}')
                    cmd.append(str(value))

        cwd = str(script_path.parent)
        lines: list[str] = []
        callback = self._callback

        try:
            proc = subprocess.Popen(
                cmd,
                stdout=subprocess.PIPE,
                stderr=subprocess.PIPE,
                cwd=cwd,
                universal_newlines=True,  # text mode: \r treated as line ending
                encoding='utf-8',
                errors='replace',
            )
        except OSError as exc:
            raise SkillScriptExecutionError(
                f"Failed to launch script '{script.name}' with python executable '{self._python_executable}'"
            ) from exc

        def _run_with_streaming(proc) -> int:
            """Run subprocess in a thread, streaming output via callback."""
            import threading

            # Synchronize access to shared `lines` across threads.
            lock = threading.Lock()

            def _read_stdout(stream):
                for line in iter(stream.readline, ''):
                    line = line.rstrip('\r\n')
                    if line.strip():
                        # Protect only the shared `lines` list with the lock.
                        with lock:
                            lines.append(line)
                        # Invoke the callback outside the critical section to avoid blocking both readers.
                        callback(line)

            def _read_stderr(stream):
                for line in iter(stream.readline, ''):
                    line = line.rstrip('\r\n')
                    if line.strip():
                        msg = "[stderr] " + line
                        # Protect only the shared `lines` list with the lock.
                        with lock:
                            lines.append(msg)
                        # Invoke the callback outside the critical section to avoid blocking both readers.
                        callback(msg)

            t_out = threading.Thread(target=_read_stdout, args=(proc.stdout,))
            t_err = threading.Thread(target=_read_stderr, args=(proc.stderr,))
            t_out.start()
            t_err.start()
            t_out.join()
            t_err.join()
            proc.wait()
            return proc.returncode

        try:
            returncode = await asyncio.wait_for(
                asyncio.to_thread(_run_with_streaming, proc),
                timeout=self.timeout,
            )
        except asyncio.TimeoutError:
            # On timeout, ensure the subprocess is terminated and reaped,
            # and that its pipes are closed so background reader threads exit.
            try:
                proc.kill()
            except ProcessLookupError:
                # Process may already have exited between timeout and kill.
                pass

            # Wait for the process to terminate and be reaped in a thread,
            # so we don't block the event loop.
            try:
                await asyncio.to_thread(proc.wait)
            except Exception:
                # Best-effort cleanup; don't mask the original timeout.
                pass

            # Close pipes so reader threads see EOF and can exit.
            for stream in (proc.stdout, proc.stderr):
                try:
                    if stream is not None and not stream.closed:
                        stream.close()
                except Exception:
                    # Ignore errors during cleanup.
                    pass
            raise SkillScriptExecutionError(
                f"Script '{script.name}' timed out after {self.timeout} seconds"
            )
        except OSError as e:
            raise SkillScriptExecutionError(f"Failed to execute script '{script.name}': {e}") from e

        output = "\n".join(lines)

        if returncode != 0:
            output += f"\n\nScript exited with code {returncode}"

        return output.strip() or "(no output)"


# ============================================================================
# GLOBAL CONTEXT & CONFIGURATION
# ============================================================================

class CLIContext:
    """Shared context for CLI commands."""

    def __init__(self):
        self.runtime: Optional[PotpieRuntime] = None
        self.default_user_id = "defaultuser"  # Use existing default user from backend
        self.config_dir = Path.home() / ".potpie"
        self.config_file = self.config_dir / "config.yaml"

    async def get_runtime(self) -> PotpieRuntime:
        """Get or initialize runtime."""
        if self.runtime is None:
            self.runtime = PotpieRuntime.from_env()
            await self.runtime.initialize()
        return self.runtime


ctx_obj = CLIContext()


# ============================================================================
# MAIN CLI GROUP
# ============================================================================

@click.group()
@click.version_option(version="0.1.0")
def cli():
    """
    🤖 Potpie CLI - Code Intelligence at Your Fingertips

    Build knowledge graphs and chat with your codebase from the command line.

    Examples:
        potpie-cli parse /path/to/repo              # Build knowledge graph
        potpie-cli chat --project <project-id>      # Interactive chat
        potpie-cli ask "How does auth work?" -p <id> # One-shot question
        potpie-cli agents                           # List available agents
    """
    pass


# ============================================================================
# PARSING COMMANDS (Knowledge Graph Construction)
# ============================================================================

@cli.group()
def parse():
    """📊 Parse repositories and build knowledge graphs."""
    pass


@parse.command(name="repo")
@click.argument('repo_path', type=click.Path(exists=True))
@click.option('--branch', '-b', default=None, help='Branch name (defaults to current git branch)')
@click.option('--user-id', '-u', default=None, help='User ID (defaults to cli-user)')
@click.option('--cleanup/--no-cleanup', default=True, help='Clean up existing graph')
@click.option('--watch', '-w', is_flag=True, help='Watch for changes and re-parse')
@click.option('--force', '-f', is_flag=True, help='Force reparse even if commit has not changed')
def parse_repo(repo_path: str, branch: Optional[str], user_id: Optional[str], cleanup: bool, watch: bool, force: bool):
    """
    Parse a repository and build its knowledge graph.

    Examples:
        potpie-cli parse repo /path/to/myproject
        potpie-cli parse repo ~/code/app --branch develop
        potpie-cli parse repo . --no-cleanup
        potpie-cli parse repo . --force
    """
    # Auto-detect current git branch if not specified
    if branch is None:
        try:
            from git import Repo as GitRepo
            branch = GitRepo(repo_path).active_branch.name
        except Exception:
            branch = 'main'
    asyncio.run(_parse_repo(repo_path, branch, user_id or ctx_obj.default_user_id, cleanup, watch, force))


async def _parse_repo(repo_path: str, branch: str, user_id: str, cleanup: bool, watch: bool, force: bool = False):
    """Implementation of parse repo command."""
    try:
        runtime = await ctx_obj.get_runtime()
        repo_path = str(Path(repo_path).expanduser().resolve())
        repo_name = Path(repo_path).name

        # Auto-detect current HEAD commit for change detection
        commit_id = None
        try:
            from git import Repo as GitRepo
            commit_id = GitRepo(repo_path).head.commit.hexsha
        except Exception:
            pass

        # --force: bypass commit change detection by not passing commit_id to register
        console.print(Panel.fit(
            f"[bold cyan]Repository:[/bold cyan] {repo_name}\n"
            f"[bold cyan]Path:[/bold cyan] {repo_path}\n"
            f"[bold cyan]Branch:[/bold cyan] {branch}\n"
            f"[bold cyan]Commit:[/bold cyan] {commit_id[:12] if commit_id else 'unknown'}\n"
            f"[bold cyan]Cleanup:[/bold cyan] {'Yes' if cleanup else 'No'}",
            title="🔨 Parsing Configuration",
            border_style="cyan"
        ))

        with Progress(
            SpinnerColumn(),
            TextColumn("[progress.description]{task.description}"),
            console=console,
        ) as progress:
            # Step 1: Register project
            task1 = progress.add_task("📝 Registering project...", total=None)

            project_id = await runtime.projects.register(
                repo_name=repo_name,
                branch_name=branch,
                user_id=user_id,
                repo_path=repo_path,
                commit_id=commit_id,
            )

            progress.update(task1, completed=True)
            console.print(f"✅ Project registered: [cyan]{project_id}[/cyan]")

            # Step 2: Parse repository
            task2 = progress.add_task(
                "🔨 Building knowledge graph (this may take several minutes)...",
                total=None
            )

            result = await runtime.parsing.parse_project(
                project_id=project_id,
                user_id=user_id,
                user_email=f"{user_id}@cli.local",
                cleanup_graph=cleanup,
                commit_id=commit_id,
                force=force,
            )

            progress.update(task2, completed=True)

        if result.success:
            # Get statistics
            node_count = await runtime.parsing.get_node_count(project_id)

            console.print("\n[bold green]✅ Parsing completed successfully![/bold green]\n")

            # Display results
            table = Table(title="📊 Parsing Results", show_header=True, header_style="bold magenta")
            table.add_column("Metric", style="cyan", width=20)
            table.add_column("Value", style="green")

            table.add_row("Project ID", project_id)
            table.add_row("Repository", repo_name)
            table.add_row("Branch", branch)
            table.add_row("Path", repo_path)
            table.add_row("Nodes Created", str(node_count))
            table.add_row("Status", "READY")

            console.print(table)

            # Save to config for quick access
            _save_last_project(project_id, repo_name)

            console.print(f"\n💡 [yellow]Quick start commands:[/yellow]")
            console.print(f"   [dim]# Interactive chat[/dim]")
            console.print(f"   potpie-cli chat -p {project_id}")
            console.print(f"   [dim]# Or use the shortcut (uses last parsed project)[/dim]")
            console.print(f"   potpie-cli chat")
            console.print(f"   [dim]# One-shot question[/dim]")
            console.print(f"   potpie-cli ask \"Explain the architecture\" -p {project_id}")

        else:
            console.print(f"[bold red]❌ Parsing failed:[/bold red] {result.error_message}")
            raise click.Abort()

    except Exception as e:
        console.print(f"[bold red]Error:[/bold red] {e}")
        raise click.Abort()


@parse.command(name="status")
@click.argument('project_id', required=False)
def parse_status(project_id: Optional[str]):
    """
    Check parsing status for a project.

    If no project ID provided, shows status of last parsed project.
    """
    asyncio.run(_parse_status(project_id))


async def _parse_status(project_id: Optional[str]):
    """Check parsing status."""
    try:
        if not project_id:
            project_id = _get_last_project()
            if not project_id:
                console.print("[yellow]No project ID provided and no recent project found.[/yellow]")
                console.print("Usage: potpie-cli parse status <project-id>")
                raise click.Abort()

        runtime = await ctx_obj.get_runtime()

        with console.status("[bold cyan]Checking status...", spinner="dots"):
            status = await runtime.parsing.get_status(project_id)
            node_count = await runtime.parsing.get_node_count(project_id)

        # Status indicator
        status_emoji = {
            "READY": "✅",
            "SUBMITTED": "⏳",
            "ERROR": "❌",
            "PENDING": "🕐"
        }.get(status.value, "❓")

        table = Table(title=f"Project Status", show_header=True, header_style="bold cyan")
        table.add_column("Property", style="cyan", width=20)
        table.add_column("Value", style="green")

        table.add_row("Project ID", project_id)
        table.add_row("Status", f"{status_emoji} {status.value}")
        table.add_row("Nodes in Graph", str(node_count))
        table.add_row("Ready for Queries", "✅ Yes" if status == ProjectStatus.READY else "❌ No")

        console.print(table)

        if status != ProjectStatus.READY:
            console.print(f"\n[yellow]💡 Project is not ready yet. Current status: {status.value}[/yellow]")

    except Exception as e:
        console.print(f"[bold red]Error:[/bold red] {e}")
        raise click.Abort()


# ============================================================================
# AGENT COMMANDS (Chat & Q&A)
# ============================================================================

@cli.command()
@click.option('--project', '-p', help='Project ID to chat about')
@click.option('--agent', '-a', default='codebase_qna_agent',
              help='Agent to use (default: codebase_qna_agent)')
def chat(project: Optional[str], agent: str):
    """
    🗣️  Start an interactive chat session with an agent.

    Examples:
        potpie-cli chat                                    # Use last project
        potpie-cli chat -p <project-id>                   # Specify project
        potpie-cli chat -p <id> -a code_generation_agent  # Use code gen agent
        potpie-cli chat -a debugging_agent                # Debug last project
    """
    asyncio.run(_chat(project, agent))


async def _chat(project_id: Optional[str], agent_id: str):
    """Interactive chat implementation."""
    try:
        if not project_id:
            project_id = _get_last_project()
            if not project_id:
                console.print("[yellow]No project specified and no recent project found.[/yellow]")
                console.print("Usage: potpie-cli chat --project <project-id>")
                console.print("Or parse a repository first: potpie-cli parse repo /path/to/repo")
                raise click.Abort()

        runtime = await ctx_obj.get_runtime()

        # Get agent handle
        try:
            agent = getattr(runtime.agents, agent_id)
        except AttributeError:
            console.print(f"[red]Agent '{agent_id}' not found.[/red]")
            console.print("Run 'potpie-cli agents' to see available agents.")
            raise click.Abort()

        # Get project info
        project_info = await runtime.projects.get(project_id)

        # Display header
        console.print(Panel.fit(
            f"[bold cyan]Agent:[/bold cyan] {agent_id}\n"
            f"[bold cyan]Project:[/bold cyan] {project_info.repo_name}\n"
            f"[bold cyan]Branch:[/bold cyan] {project_info.branch_name}\n"
            f"[bold cyan]Project ID:[/bold cyan] {project_id}\n\n"
            f"[dim]Type 'exit', 'quit', or 'q' to end the session[/dim]",
            title="🤖 Potpie Chat Session",
            border_style="cyan"
        ))

        history = []
        MAX_HISTORY_TURNS = 5  # Keep only last 5 conversation turns to avoid token limit

        while True:
            try:
                query = console.input("\n[bold blue]You:[/bold blue] ")
            except (KeyboardInterrupt, EOFError):
                console.print("\n[yellow]Goodbye! 👋[/yellow]")
                break

            if query.lower().strip() in ["exit", "quit", "q"]:
                console.print("[yellow]Goodbye! 👋[/yellow]")
                break

            if not query.strip():
                continue

            # Create context
            ctx = ChatContext(
                project_id=project_id,
                project_name=project_info.repo_name,
                curr_agent_id=agent_id,
                query=query,
                history=history,
                user_id=ctx_obj.default_user_id
            )

            console.print("[bold green]🤖 Agent:[/bold green] ", end="")

            response_text = ""
            try:
                async for chunk in agent.stream(ctx):
                    console.print(chunk.response, end="", markup=False)
                    response_text += chunk.response

                console.print()  # New line after response

                # Update history (keep only recent turns to avoid token limit)
                history.append({"role": "user", "content": query})
                history.append({"role": "assistant", "content": response_text})

                # Trim history to prevent token overflow
                if len(history) > MAX_HISTORY_TURNS * 2:  # Each turn = 2 messages
                    history = history[-MAX_HISTORY_TURNS * 2:]

            except Exception as e:
                console.print(f"\n[red]Error during agent execution: {e}[/red]")

    except Exception as e:
        console.print(f"[bold red]Error:[/bold red] {e}")
        raise click.Abort()


@cli.command()
@click.argument('query')
@click.option('--project', '-p', help='Project ID')
@click.option('--agent', '-a', default='codebase_qna_agent', help='Agent to use')
@click.option('--markdown/--no-markdown', default=True, help='Render as markdown')
@click.option('--json', 'output_json', is_flag=True, help='Output in JSON format with answer and source files')
def ask(query: str, project: Optional[str], agent: str, markdown: bool, output_json: bool):
    """
    ❓ Ask a one-shot question to an agent.

    Examples:
        potpie-cli ask "How does authentication work?"
        potpie-cli ask "Explain the main function" -p <project-id>
        potpie-cli ask "Find all API endpoints" -a codebase_qna_agent
        potpie-cli ask "How does auth work?" --json
    """
    asyncio.run(_ask(query, project, agent, markdown, output_json))


async def _ask(query: str, project_id: Optional[str], agent_id: str, render_markdown: bool, output_json: bool = False):
    """One-shot question implementation."""
    try:
        if not project_id:
            project_id = _get_last_project()
            if not project_id:
                if output_json:
                    print(json.dumps({"error": "No project specified. Use --project <id> or parse a repo first."}))
                else:
                    console.print("[yellow]No project specified. Use --project <id> or parse a repo first.[/yellow]")
                raise click.Abort()

        runtime = await ctx_obj.get_runtime()

        # Get agent
        try:
            agent = getattr(runtime.agents, agent_id)
        except AttributeError:
            if output_json:
                print(json.dumps({"error": f"Agent '{agent_id}' not found."}))
            else:
                console.print(f"[red]Agent '{agent_id}' not found.[/red]")
            raise click.Abort()

        # Get project info
        project_info = await runtime.projects.get(project_id)

        if not output_json:
            console.print(f"\n[bold cyan]Question:[/bold cyan] {query}")
            console.print(f"[dim]Project: {project_info.repo_name} | Agent: {agent_id}[/dim]\n")

        # Create context
        ctx = ChatContext(
            project_id=project_id,
            project_name=project_info.repo_name,
            curr_agent_id=agent_id,
            query=f"[Codebase: {project_info.repo_name}, project_id: {project_id}] {query}",
            history=[],
            user_id=ctx_obj.default_user_id,
        )

        if not output_json:
            with console.status("[bold cyan]Agent is thinking...", spinner="dots"):
                response = await agent.query(ctx)
        else:
            response = await agent.query(ctx)

        if output_json:
            # Build JSON output with answer and source files
            import json
            result = {
                "answer": response.response,
                "sources": []
            }

            # Extract source files from tool calls
            for tool_call in response.tool_calls:
                if tool_call.event_type.value == "result":
                    tool_details = tool_call.tool_call_details
                    # Check if this is a code search or file retrieval / graph tool
                    if tool_call.tool_name in [
                        # Legacy / older tool names (kept for compatibility)
                        "search_code",
                        "get_code",
                        "get_node_from_code",
                        "get_node_from_node_id",
                        # Current repo tool names
                        "fetch_file",
                        "fetch_files_batch",
                        "get_code_from_node_id",
                        "get_code_from_multiple_node_ids",
                        "get_code_from_probable_node_name",
                        "get_code_file_structure",
                        "ask_knowledge_graph_queries",
                    ]:
                        # Extract file path and content from tool response
                        file_info = {
                            "tool": tool_call.tool_name,
                            "content": tool_call.tool_response
                        }
                        # Try to extract file path from tool_call_details
                        if "file_path" in tool_details:
                            file_info["file"] = tool_details["file_path"]
                        elif "node_id" in tool_details:
                            file_info["node_id"] = tool_details["node_id"]

                        result["sources"].append(file_info)

            # Also include citations
            if response.citations:
                result["citations"] = response.citations

            print(json.dumps(result, indent=2))
        else:
            console.print("[bold green]🤖 Answer:[/bold green]\n")

            if render_markdown:
                md = Markdown(response.response)
                console.print(md)
            else:
                console.print(response.response)

            console.print()

    except Exception as e:
        if output_json:
            import json
            print(json.dumps({"error": str(e)}))
        else:
            console.print(f"[bold red]Error:[/bold red] {e}")
        raise click.Abort()


@cli.command()
@click.argument('description')
@click.option('--project', '-p', help='Project ID')
@click.option('--preview', is_flag=True, help='Preview changes without applying')
def code(description: str, project: Optional[str], preview: bool):
    """
    💻 Generate code changes using the code generation agent.

    Examples:
        potpie-cli code "Add error handling to user service"
        potpie-cli code "Create a new API endpoint for users" -p <id>
        potpie-cli code "Refactor authentication module" --preview
    """
    asyncio.run(_code(description, project, preview))


async def _code(description: str, project_id: Optional[str], preview: bool):
    """Code generation implementation."""
    try:
        if not project_id:
            project_id = _get_last_project()
            if not project_id:
                console.print("[yellow]No project specified.[/yellow]")
                raise click.Abort()

        runtime = await ctx_obj.get_runtime()
        agent = runtime.agents.code_generation_agent
        project_info = await runtime.projects.get(project_id)

        console.print(f"\n[bold cyan]Task:[/bold cyan] {description}")
        console.print(f"[dim]Project: {project_info.repo_name}[/dim]\n")

        ctx = ChatContext(
            project_id=project_id,
            project_name=project_info.repo_name,
            curr_agent_id=agent.id,
            query=description,
            history=[],
            user_id=ctx_obj.default_user_id
        )

        console.print("[bold green]🤖 Code Agent:[/bold green]\n")

        async for chunk in agent.stream(ctx):
            console.print(chunk.response, end="", markup=False)

        console.print("\n")

        if preview:
            console.print("[yellow]Preview mode - no changes applied[/yellow]")

    except Exception as e:
        console.print(f"[bold red]Error:[/bold red] {e}")
        raise click.Abort()


@cli.command()
@click.option('--repo-name', '-r', required=True,
              help='Repository name (as registered in potpie)')
@click.option('--branch', '-b', default='main', show_default=True,
              help='Branch name')
@click.option('--output-dir', '-o', default=None,
              help='Output directory for wiki pages (default: <repo_path>/.repowiki)')
@click.option('--skills-dir', default='.kiro/skills', show_default=True,
              help='Directory containing skill definitions')
@click.option('--timeout', '-t', default=1200, show_default=True, type=int,
              help='Timeout in seconds for the skill script executor')
@click.option('--verbose', '-v', is_flag=True, default=False,
              help='Show debug logging')
def wiki(repo_name: str, branch: str, output_dir: Optional[str],
         skills_dir: str, timeout: int, verbose: bool):
    """
    📖 Generate wiki documentation for a repository using the repowiki skill.

    Examples:
        potpie-cli wiki -r device-modeling-language -b main
        potpie-cli wiki -r myrepo -b develop -o docs/wiki
        potpie-cli wiki -r myrepo --timeout 1800
    """
    asyncio.run(_wiki(repo_name, branch, output_dir, skills_dir, timeout, verbose))


async def _wiki(repo_name: str, branch: str, output_dir: Optional[str],
                skills_dir: str, timeout: int, verbose: bool):
    """Wiki generation via repowiki skill — mirrors _eval pattern."""
    import os
    from pydantic_ai import Agent, RunContext
    from pydantic_ai_skills import SkillsToolset
    from pydantic_ai_skills.directory import SkillsDirectory
    from pydantic_ai_skills.local import LocalSkillScriptExecutor
    from app.modules.intelligence.provider.litellm_model import LiteLLMModel

    def dbg(msg):
        if verbose:
            console.print(f"[dim]{msg}[/dim]")

    # Resolve project
    runtime = await ctx_obj.get_runtime()
    projects = await runtime.projects.list(user_id=ctx_obj.default_user_id)
    matches = [p for p in projects if p.repo_name == repo_name and p.branch_name == branch]
    if not matches:
        console.print(f"[bold red]Error:[/bold red] No project found for repo='{repo_name}' branch='{branch}'.")
        all_branches = [p.branch_name for p in projects if p.repo_name == repo_name]
        if all_branches:
            console.print(f"[yellow]Available branches for '{repo_name}': {all_branches}[/yellow]")
        raise click.Abort()

    project = matches[0]
    repo_path = project.repo_path

    if not repo_path:
        try:
            repo_path = await runtime.repositories.get_path(
                repo_name, ctx_obj.default_user_id, branch=branch
            )
        except Exception:
            repo_path = None

    if not repo_path:
        candidate = Path(repo_name)
        if candidate.exists():
            repo_path = str(candidate.absolute())

    if not repo_path:
        console.print(f"[bold red]Error:[/bold red] Could not resolve local path for repo='{repo_name}' branch='{branch}'.")
        raise click.Abort()

    if output_dir is None:
        output_dir = str(Path(repo_path) / ".repowiki")
    else:
        output_dir = str(Path(output_dir).expanduser().resolve())

    skills_path = Path(skills_dir)
    if not skills_path.is_absolute():
        skills_path = Path(__file__).parent / skills_path

    console.print(Panel.fit(
        f"[bold cyan]Repository:[/bold cyan] {repo_name}\n"
        f"[bold cyan]Branch:[/bold cyan] {branch}\n"
        f"[bold cyan]Project ID:[/bold cyan] {project.id}\n"
        f"[bold cyan]Path:[/bold cyan] {repo_path}\n"
        f"[bold cyan]Output:[/bold cyan] {output_dir}",
        title="📖 Wiki Generation",
        border_style="cyan"
    ))

    user_prompt = (
        f"Generate wiki documentation for the repository.\n"
        f"Use the repowiki skill's generate_wiki script with these args:\n"
        f"  project_id: '{project.id}'\n"
        f"  repo_path: '{repo_path}'\n"
        f"  output_dir: '{output_dir}'\n"
        f"\nIMPORTANT: run_skill_script takes args as a dict, not a list."
        f" Use: skill_name='repowiki', script_name='scripts/generate_wiki.py',"
        f" args={{'project_id': '{project.id}', 'repo_path': '{repo_path}', 'output_dir': '{output_dir}'}}"
    )

    model_name = os.environ.get("CHAT_MODEL", "github_copilot/gpt-4o")
    model = LiteLLMModel(model_name)

    if verbose:
        executor = StreamingLocalSkillScriptExecutor(
            callback=_verbose_skill_stream_callback(),
            timeout=timeout,
        )
    else:
        executor = LocalSkillScriptExecutor(timeout=timeout)
    skills_dir_obj = SkillsDirectory(path=str(skills_path), script_executor=executor)
    skills_toolset = SkillsToolset(directories=[skills_dir_obj])

    agent = Agent(
        model=model,
        instructions="You are a technical documentation expert.",
        toolsets=[skills_toolset],
    )

    @agent.instructions
    async def add_skills(ctx: RunContext) -> str | None:
        return await skills_toolset.get_instructions(ctx)

    console.print(f"\n[bold cyan]📖 Running wiki generation via repowiki skill[/bold cyan]\n")
    dbg(f"Prompt: {user_prompt}")

    async with agent.iter(user_prompt) as agent_run:
        dbg("Agent started, iterating nodes...")
        async for node in agent_run:
            dbg(f"Node: {type(node).__name__}")
            if Agent.is_call_tools_node(node):
                for part in node.model_response.parts:
                    if hasattr(part, "tool_name"):
                        console.print(f"\n[dim cyan]🔧 {part.tool_name}[/dim cyan]")
                        if verbose and hasattr(part, "args"):
                            dbg(f"  args: {part.args}")
            elif Agent.is_end_node(node):
                console.print(f"\n[bold green]✅ Done:[/bold green]\n")
                console.print(Markdown(str(node.data.output)))


@cli.command()
@click.option('--repo', '-r', required=True, type=click.Path(exists=True),
              help='Path to repository to generate wiki for')
@click.option('--project', '-p', help='Project ID (if already parsed)')
@click.option('--concise', is_flag=True, help='Generate concise wiki (4-6 pages instead of 8-12)')
@click.option('--readme', type=str, help='Path to README.md relative to repository root (e.g., "README.md" or "docs/README.md")')
def deepwiki_open_wiki(repo: str, project: Optional[str], concise: bool, readme: Optional[str]):
    """
    📚 Generate comprehensive wiki using deepwiki-open methodology.

    This command uses the DeepWikiOpenAgent to generate structured wiki documentation
    following the deepwiki-open workflow: analyze structure, plan pages, generate content.

    Examples:
        potpie-cli deepwiki-open-wiki --repo /path/to/repo
        potpie-cli deepwiki-open-wiki -r . -p <project-id>
        potpie-cli deepwiki-open-wiki -r ~/myproject --concise
        potpie-cli deepwiki-open-wiki -r . --readme README.md
    """
    asyncio.run(_deepwiki_open_wiki(repo, project, concise, readme))


async def _deepwiki_open_wiki(repo_path: str, project_id: Optional[str], concise: bool, readme_path: Optional[str]):
    """DeepWiki Open wiki generation implementation."""
    try:
        runtime = await ctx_obj.get_runtime()
        repo_path = str(Path(repo_path).expanduser().resolve())
        repo_name = Path(repo_path).name

        # Read README if provided
        readme_content = None
        if readme_path:
            # Resolve relative to repo path
            full_readme_path = Path(repo_path) / readme_path
            try:
                with open(full_readme_path, 'r', encoding='utf-8') as f:
                    readme_content = f.read()
                console.print(f"[green]✅ README loaded from {readme_path}[/green]")
            except Exception as e:
                console.print(f"[yellow]⚠️  Failed to read README at {readme_path}: {e}[/yellow]")

        # If no project ID, try to parse the repo first
        if not project_id:
            console.print("[yellow]No project ID provided. Parsing repository first...[/yellow]")

            # Auto-detect branch
            try:
                from git import Repo as GitRepo
                branch = GitRepo(repo_path).active_branch.name
                commit_id = GitRepo(repo_path).head.commit.hexsha
            except Exception:
                branch = 'main'
                commit_id = None

            with Progress(
                SpinnerColumn(),
                TextColumn("[progress.description]{task.description}"),
                console=console,
            ) as progress:
                task = progress.add_task("📝 Registering and parsing project...", total=None)

                project_id = await runtime.projects.register(
                    repo_name=repo_name,
                    branch_name=branch,
                    user_id=ctx_obj.default_user_id,
                    repo_path=repo_path,
                    commit_id=commit_id,
                )

                result = await runtime.parsing.parse_project(
                    project_id=project_id,
                    user_id=ctx_obj.default_user_id,
                    user_email=f"{ctx_obj.default_user_id}@cli.local",
                    cleanup_graph=True,
                    commit_id=commit_id,
                )

                progress.update(task, completed=True)

            if not result.success:
                console.print(f"[bold red]❌ Parsing failed:[/bold red] {result.error_message}")
                raise click.Abort()

            console.print(f"[bold green]✅ Project parsed successfully![/bold green] ID: {project_id}\n")

        # Get agent
        try:
            agent = runtime.agents.deepwiki_open_agent
        except AttributeError:
            console.print("[red]deepwiki_open_agent not found. Make sure it is registered in agents_service.py.[/red]")
            raise click.Abort()

        project_info = await runtime.projects.get(project_id)

        # Build query based on mode
        mode = "concise" if concise else "comprehensive"
        query = f"Generate {mode} wiki documentation for the entire repository following deepwiki-open methodology"

        console.print(Panel.fit(
            f"[bold cyan]Repository:[/bold cyan] {repo_name}\n"
            f"[bold cyan]Path:[/bold cyan] {repo_path}\n"
            f"[bold cyan]Project ID:[/bold cyan] {project_id}\n"
            f"[bold cyan]Mode:[/bold cyan] {'Concise (4-6 pages)' if concise else 'Comprehensive (8-12 pages)'}\n"
            f"[bold cyan]README:[/bold cyan] {'Provided' if readme_content else 'Not provided'}\n"
            f"[bold cyan]Output:[/bold cyan] .repowiki/en/content/",
            title="📚 DeepWiki Open Generation",
            border_style="cyan"
        ))

        ctx = ChatContext(
            project_id=project_id,
            project_name=project_info.repo_name,
            curr_agent_id="deepwiki_open_agent",
            query=f"[Codebase: {project_info.repo_name}, project_id: {project_id}] {query}",
            history=[],
            user_id=ctx_obj.default_user_id,
            conversation_id=f"deepwiki_{project_id}",
        )

        # Add README content to context if provided
        if readme_content:
            ctx.additional_context = f"\n\nREADME Content:\n{readme_content}\n"

        console.print("\n[bold green]🤖 DeepWiki Open Agent:[/bold green] generating...\n")

        from potpie.agents.context import ToolCallEventType
        pages_written = []
        async for chunk in agent.stream(ctx):
            if chunk.tool_calls:
                for tc in chunk.tool_calls:
                    if tc.event_type == ToolCallEventType.CALL:
                        console.print(f"\n[dim cyan]🔧 {tc.tool_name}[/dim cyan]", end="", markup=True)
            if chunk.response:
                console.print(chunk.response, end="", markup=False)
                if "✅ Wiki page written to:" in chunk.response:
                    for line in chunk.response.splitlines():
                        if "✅ Wiki page written to:" in line:
                            pages_written.append(line.split("✅ Wiki page written to:")[-1].strip())

        console.print("\n")

        if pages_written:
            console.print(f"\n[bold green]✅ {len(pages_written)} wiki page(s) written:[/bold green]")
            for p in pages_written:
                console.print(f"   [cyan]{p}[/cyan]")
        else:
            console.print("[yellow]Wiki generation complete. Check .repowiki/en/content/ for output.[/yellow]")

    except Exception as e:
        console.print(f"[bold red]Error:[/bold red] {e}")
        raise click.Abort()


@cli.command()
def agents():
    """
    📋 List all available agents and their descriptions.
    """
    asyncio.run(_list_agents())


async def _list_agents():
    """List available agents."""
    try:
        runtime = await ctx_obj.get_runtime()
        agents = runtime.agents.list_agents()

        table = Table(title="🤖 Available Agents", show_header=True, header_style="bold magenta")
        table.add_column("Agent ID", style="cyan", width=30)
        table.add_column("Name", style="green", width=25)
        table.add_column("Description", style="white")

        for agent in agents:
            table.add_row(agent.id, agent.name, agent.description)

        console.print(table)

        console.print(f"\n💡 [yellow]Usage:[/yellow]")
        console.print(f"   potpie-cli chat --agent <agent-id>")
        console.print(f"   potpie-cli ask \"question\" --agent <agent-id>")

    except Exception as e:
        console.print(f"[bold red]Error:[/bold red] {e}")
        raise click.Abort()


# ============================================================================
# PROJECT MANAGEMENT COMMANDS
# ============================================================================

@cli.group()
def projects():
    """
    📁 Manage projects (list, remove, etc.).
    """
    pass


@projects.command(name="list")
@click.option('--user-id', '-u', help='Filter by user ID')
def list_projects_cmd(user_id: Optional[str]):
    """
    📁 List all registered projects.
    """
    asyncio.run(_list_projects(user_id or ctx_obj.default_user_id))


async def _list_projects(user_id: str):
    """List all projects."""
    try:
        runtime = await ctx_obj.get_runtime()
        projects = await runtime.projects.list(user_id=user_id)

        if not projects:
            console.print("[yellow]No projects found.[/yellow]")
            console.print("Parse a repository first: potpie-cli parse repo /path/to/repo")
            return

        table = Table(title="📁 Registered Projects", show_header=True, header_style="bold cyan")
        table.add_column("Project ID", style="cyan", width=38)
        table.add_column("Name", style="green", width=25)
        table.add_column("Branch", style="blue", width=15)
        table.add_column("Status", style="magenta", width=12)

        for project in projects:
            status_emoji = {
                "READY": "✅",
                "SUBMITTED": "⏳",
                "ERROR": "❌"
            }.get(project.status.value, "❓")

            table.add_row(
                project.id,
                project.repo_name,
                project.branch_name,
                f"{status_emoji} {project.status.value}",
            )

        console.print(table)

    except Exception as e:
        console.print(f"[bold red]Error:[/bold red] {e}")
        raise click.Abort()


@projects.command(name="remove")
@click.argument('project_id')
@click.option('--force', '-f', is_flag=True, help='Skip confirmation prompt')
def remove_project_cmd(project_id: str, force: bool):
    """
    🗑️  Remove a project and its associated data.

    Examples:
        potpie-cli projects remove <project-id>
        potpie-cli projects remove <project-id> --force
    """
    asyncio.run(_remove_project(project_id, force))


@projects.command(name="remove-all")
@click.option('--user-id', '-u', help='Filter by user ID')
@click.option('--force', '-f', is_flag=True, help='Skip confirmation prompt')
def remove_all_projects_cmd(user_id: Optional[str], force: bool):
    """
    🗑️  Remove all projects and their associated data.

    Examples:
        potpie-cli projects remove-all
        potpie-cli projects remove-all --user-id <user-id>
        potpie-cli projects remove-all --force
    """
    asyncio.run(_remove_all_projects(user_id or ctx_obj.default_user_id, force))


async def _remove_project(project_id: str, force: bool):
    """Remove a project implementation."""
    try:
        runtime = await ctx_obj.get_runtime()

        # Get project info first to display details
        project_info = await runtime.projects.get(project_id)

        if project_info is None:
            console.print(f"[bold red]Error:[/bold red] Project '{project_id}' not found.")
            raise click.Abort()

        # Show what will be deleted
        console.print(Panel.fit(
            f"[bold cyan]Project ID:[/bold cyan] {project_info.id}\n"
            f"[bold cyan]Name:[/bold cyan] {project_info.repo_name}\n"
            f"[bold cyan]Branch:[/bold cyan] {project_info.branch_name}\n"
            f"[bold cyan]Status:[/bold cyan] {project_info.status.value}",
            title="🗑️  Project to Remove",
            border_style="red"
        ))

        # Confirm deletion unless --force is used
        if not force:
            console.print("\n[bold yellow]⚠️  Warning:[/bold yellow] This will delete the project and all associated data from the knowledge graph.")
            confirmation = console.input("[bold red]Are you sure you want to proceed? (yes/no):[/bold red] ")

            if confirmation.lower() not in ['yes', 'y']:
                console.print("[yellow]Deletion cancelled.[/yellow]")
                return

        # Perform deletion
        with console.status("[bold cyan]Deleting project...", spinner="dots"):
            await runtime.projects.delete(project_id)

        console.print(f"\n[bold green]✅ Project '{project_info.repo_name}' successfully deleted![/bold green]")

        # Clear from config if this was the last used project
        last_project = _get_last_project()
        if last_project == project_id:
            import yaml
            ctx_obj.config_dir.mkdir(exist_ok=True)
            config = {}
            if ctx_obj.config_file.exists():
                with open(ctx_obj.config_file) as f:
                    config = yaml.safe_load(f) or {}
            if 'last_project' in config:
                del config['last_project']
                with open(ctx_obj.config_file, 'w') as f:
                    yaml.dump(config, f)
                console.print("[dim]Cleared from last used project cache.[/dim]")

    except click.Abort:
        raise
    except Exception as e:
        console.print(f"[bold red]Error:[/bold red] {e}")
        raise click.Abort()


async def _remove_all_projects(user_id: str, force: bool):
    """Remove all projects implementation."""
    try:
        runtime = await ctx_obj.get_runtime()

        # Get all projects for the user
        projects = await runtime.projects.list(user_id=user_id)

        if not projects:
            console.print("[yellow]No projects found to remove.[/yellow]")
            return

        # Show what will be deleted
        console.print(f"\n[bold red]Found {len(projects)} project(s) to remove:[/bold red]\n")

        table = Table(show_header=True, header_style="bold cyan", border_style="red")
        table.add_column("Project ID", style="cyan", width=38)
        table.add_column("Name", style="green", width=25)
        table.add_column("Branch", style="blue", width=15)
        table.add_column("Status", style="magenta", width=12)

        for project in projects:
            status_emoji = {
                "READY": "✅",
                "SUBMITTED": "⏳",
                "ERROR": "❌"
            }.get(project.status.value, "❓")

            table.add_row(
                project.id,
                project.repo_name,
                project.branch_name,
                f"{status_emoji} {project.status.value}",
            )

        console.print(table)

        # Confirm deletion unless --force is used
        if not force:
            console.print("\n[bold yellow]⚠️  Warning:[/bold yellow] This will delete ALL projects and their associated data from the knowledge graph.")
            confirmation = console.input(f"[bold red]Type 'DELETE ALL' to confirm removal of {len(projects)} project(s):[/bold red] ")

            if confirmation != 'DELETE ALL':
                console.print("[yellow]Deletion cancelled.[/yellow]")
                return

        # Perform deletion
        deleted_count = 0
        failed_count = 0

        with Progress(
            SpinnerColumn(),
            TextColumn("[progress.description]{task.description}"),
            console=console
        ) as progress:
            task = progress.add_task(f"[cyan]Deleting {len(projects)} project(s)...", total=len(projects))

            for project in projects:
                try:
                    await runtime.projects.delete(project.id)
                    deleted_count += 1
                    progress.update(task, advance=1, description=f"[cyan]Deleted {deleted_count}/{len(projects)} projects...")
                except Exception as e:
                    console.print(f"[bold red]Failed to delete project '{project.repo_name}':[/bold red] {e}")
                    failed_count += 1
                    progress.update(task, advance=1)

        # Summary
        console.print(f"\n[bold green]✅ Successfully deleted {deleted_count} project(s)![/bold green]")
        if failed_count > 0:
            console.print(f"[bold red]❌ Failed to delete {failed_count} project(s).[/bold red]")

        # Clear last project from config
        import yaml
        ctx_obj.config_dir.mkdir(exist_ok=True)
        config = {}
        if ctx_obj.config_file.exists():
            with open(ctx_obj.config_file) as f:
                config = yaml.safe_load(f) or {}
        if 'last_project' in config:
            del config['last_project']
            with open(ctx_obj.config_file, 'w') as f:
                yaml.dump(config, f)
            console.print("[dim]Cleared last used project cache.[/dim]")

    except click.Abort:
        raise
    except Exception as e:
        console.print(f"[bold red]Error:[/bold red] {e}")
        raise click.Abort()


# ============================================================================
# UTILITY FUNCTIONS
# ============================================================================

def _save_last_project(project_id: str, project_name: str):
    """Save last used project to config."""
    import yaml

    ctx_obj.config_dir.mkdir(exist_ok=True)

    config = {}
    if ctx_obj.config_file.exists():
        with open(ctx_obj.config_file) as f:
            config = yaml.safe_load(f) or {}

    config['last_project'] = {
        'id': project_id,
        'name': project_name
    }

    with open(ctx_obj.config_file, 'w') as f:
        yaml.dump(config, f)


def _get_last_project() -> Optional[str]:
    """Get last used project ID from config."""
    import yaml

    if not ctx_obj.config_file.exists():
        return None

    try:
        with open(ctx_obj.config_file) as f:
            config = yaml.safe_load(f) or {}
        return config.get('last_project', {}).get('id')
    except Exception:
        return None


# ============================================================================
# EVAL COMMAND
# ============================================================================

@cli.command()
@click.option("--prompt", default="evaluation/qna/prompt.txt", show_default=True,
              help="Path to prompt file describing the evaluation task")
@click.option("--skills-dir", default=".kiro/skills", show_default=True,
              help="Directory containing skill definitions")
@click.option("--timeout", "-t", default=600, show_default=True, type=int,
              help="Timeout in seconds for the skill script executor")
@click.option("--verbose", "-v", is_flag=True, default=False,
              help="Show debug logging (node types, executor steps, tool args)")
def eval(prompt: str, skills_dir: str, timeout: int, verbose: bool):
    """
    🧪 Evaluate agent response quality using the potpie-evaluator skill.

    Uses pydantic-ai-skills to load the potpie-evaluator skill and runs
    the evaluation task described in the prompt file.

    Examples:
        potpie-cli eval
        potpie-cli eval --verbose
        potpie-cli eval --prompt evaluation/qna/prompt.txt
        potpie-cli eval --skills-dir .kiro/skills
        potpie-cli eval --timeout 900
    """
    asyncio.run(_eval(prompt, skills_dir, timeout, verbose))


async def _eval(prompt_path: str, skills_dir: str, timeout: int = 600, verbose: bool = False):
    import os
    from pydantic_ai import Agent, RunContext
    from pydantic_ai_skills import SkillsToolset
    from pydantic_ai_skills.directory import SkillsDirectory
    from app.modules.intelligence.provider.litellm_model import LiteLLMModel

    def dbg(msg):
        if verbose:
            console.print(f"[dim]{msg}[/dim]")

    # Read the prompt
    prompt_file = Path(prompt_path)
    if not prompt_file.is_absolute():
        prompt_file = Path(__file__).parent / prompt_file
    if not prompt_file.exists():
        console.print(f"[bold red]Error:[/bold red] Prompt file not found: {prompt_path}")
        raise click.Abort()
    user_prompt = prompt_file.read_text().strip()

    # Resolve any relative file paths in the prompt to absolute, so the skill
    # script can find them regardless of its working directory
    repo_root = str(Path(__file__).parent)
    cases_abs = str(Path(__file__).parent / "evaluation/qna/qna_eval_dml_cases.yaml")
    user_prompt = user_prompt + (
        f"\n\nIMPORTANT: run_skill_script takes args as a dict, not a list."
        f" Use: skill_name='potpie-evaluator', script_name='scripts/evaluate_qna.py',"
        f" args={{'cases': '{cases_abs}', 'repo': 'device-modeling-language'}}"
    )

    # Resolve skills directory relative to repo root
    skills_path = Path(skills_dir)
    if not skills_path.is_absolute():
        skills_path = Path(__file__).parent / skills_path

    # Build model — use LiteLLMModel with the configured CHAT_MODEL
    model_name = os.environ.get("CHAT_MODEL", "github_copilot/gpt-4o")
    from pydantic_ai_skills.local import LocalSkillScriptExecutor
    model = LiteLLMModel(model_name)

    if verbose:
        executor = StreamingLocalSkillScriptExecutor(
            callback=_verbose_skill_stream_callback(),
            timeout=timeout,
        )
    else:
        executor = LocalSkillScriptExecutor(timeout=timeout)
    skills_dir_obj = SkillsDirectory(path=str(skills_path), script_executor=executor)
    skills_toolset = SkillsToolset(directories=[skills_dir_obj])

    agent = Agent(
        model=model,
        instructions="You are a helpful evaluation assistant.",
        toolsets=[skills_toolset],
    )

    @agent.instructions
    async def add_skills(ctx: RunContext) -> str | None:
        return await skills_toolset.get_instructions(ctx)

    console.print(f"\n[bold cyan]🧪 Running eval via pydantic-ai-skills[/bold cyan]")
    console.print(f"[dim]Prompt: {user_prompt}[/dim]\n")
    dbg("Building agent...")

    async with agent.iter(user_prompt) as agent_run:
        dbg("Agent started, iterating nodes...")
        async for node in agent_run:
            dbg(f"Node: {type(node).__name__}")
            if Agent.is_call_tools_node(node):
                for part in node.model_response.parts:
                    if hasattr(part, "tool_name"):
                        console.print(f"\n[dim cyan]🔧 {part.tool_name}[/dim cyan]")
                        if verbose and hasattr(part, "args"):
                            dbg(f"  args: {part.args}")
            elif Agent.is_end_node(node):
                console.print(f"\n[bold green]✅ Result:[/bold green]\n")
                console.print(Markdown(str(node.data.output)))


# ============================================================================
# MAIN ENTRY POINT
# ============================================================================

if __name__ == "__main__":
    try:
        cli()
    except KeyboardInterrupt:
        console.print("\n[yellow]Interrupted by user[/yellow]")
        sys.exit(130)
