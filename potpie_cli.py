#!/usr/bin/env python3
"""
Potpie CLI - Complete command-line interface for code intelligence

Combines both graph construction and agent interactions in a single tool.
"""
import asyncio
import sys
from pathlib import Path
from typing import Optional

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
        potpie parse /path/to/repo              # Build knowledge graph
        potpie chat --project <project-id>      # Interactive chat
        potpie ask "How does auth work?" -p <id> # One-shot question
        potpie agents                           # List available agents
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
        potpie parse repo /path/to/myproject
        potpie parse repo ~/code/app --branch develop
        potpie parse repo . --no-cleanup
        potpie parse repo . --force
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

        # Auto-detect current HEAD commit for change detection (skip if --force)
        commit_id = None
        if not force:
            try:
                from git import Repo as GitRepo
                commit_id = GitRepo(repo_path).head.commit.hexsha
            except Exception:
                pass
        
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
            console.print(f"   potpie chat -p {project_id}")
            console.print(f"   [dim]# Or use the shortcut (uses last parsed project)[/dim]")
            console.print(f"   potpie chat")
            console.print(f"   [dim]# One-shot question[/dim]")
            console.print(f"   potpie ask \"Explain the architecture\" -p {project_id}")
            
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
                console.print("Usage: potpie parse status <project-id>")
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
        potpie chat                                    # Use last project
        potpie chat -p <project-id>                   # Specify project
        potpie chat -p <id> -a code_generation_agent  # Use code gen agent
        potpie chat -a debugging_agent                # Debug last project
    """
    asyncio.run(_chat(project, agent))


async def _chat(project_id: Optional[str], agent_id: str):
    """Interactive chat implementation."""
    try:
        if not project_id:
            project_id = _get_last_project()
            if not project_id:
                console.print("[yellow]No project specified and no recent project found.[/yellow]")
                console.print("Usage: potpie chat --project <project-id>")
                console.print("Or parse a repository first: potpie parse repo /path/to/repo")
                raise click.Abort()
        
        runtime = await ctx_obj.get_runtime()
        
        # Get agent handle
        try:
            agent = getattr(runtime.agents, agent_id)
        except AttributeError:
            console.print(f"[red]Agent '{agent_id}' not found.[/red]")
            console.print("Run 'potpie agents' to see available agents.")
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
def ask(query: str, project: Optional[str], agent: str, markdown: bool):
    """
    ❓ Ask a one-shot question to an agent.
    
    Examples:
        potpie ask "How does authentication work?"
        potpie ask "Explain the main function" -p <project-id>
        potpie ask "Find all API endpoints" -a codebase_qna_agent
    """
    asyncio.run(_ask(query, project, agent, markdown))


async def _ask(query: str, project_id: Optional[str], agent_id: str, render_markdown: bool):
    """One-shot question implementation."""
    try:
        if not project_id:
            project_id = _get_last_project()
            if not project_id:
                console.print("[yellow]No project specified. Use --project <id> or parse a repo first.[/yellow]")
                raise click.Abort()
        
        runtime = await ctx_obj.get_runtime()
        
        # Get agent
        try:
            agent = getattr(runtime.agents, agent_id)
        except AttributeError:
            console.print(f"[red]Agent '{agent_id}' not found.[/red]")
            raise click.Abort()
        
        # Get project info
        project_info = await runtime.projects.get(project_id)
        
        console.print(f"\n[bold cyan]Question:[/bold cyan] {query}")
        console.print(f"[dim]Project: {project_info.repo_name} | Agent: {agent_id}[/dim]\n")
        
        # Create context
        ctx = ChatContext(
            project_id=project_id,
            project_name=project_info.repo_name,
            curr_agent_id=agent_id,
            query=query,
            history=[],
            user_id=ctx_obj.default_user_id
        )
        
        with console.status("[bold cyan]Agent is thinking...", spinner="dots"):
            response = await agent.query(ctx)
        
        console.print("[bold green]🤖 Answer:[/bold green]\n")
        
        if render_markdown:
            md = Markdown(response.response)
            console.print(md)
        else:
            console.print(response.response)
        
        console.print()
        
    except Exception as e:
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
        potpie code "Add error handling to user service"
        potpie code "Create a new API endpoint for users" -p <id>
        potpie code "Refactor authentication module" --preview
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
            curr_agent_id=agent_id,
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
@click.option('--project', '-p', help='Project ID')
@click.option('--query', '-q',
              default=None,
              help='Custom wiki generation instruction')
@click.option('--section', '-s', default=None,
              help='Generate only a specific section, e.g. "Core Architecture"')
def wiki(project: Optional[str], query: str, section: Optional[str]):
    """
    📖 Generate wiki pages for a project into .qoder/repowiki/.

    Examples:
        potpie wiki                                      # Generate full wiki for last project
        potpie wiki -p <project-id>                      # Specify project
        potpie wiki -s "Core Architecture"               # One section only
        potpie wiki -q "Document the auth module only"   # Custom instruction
    """
    if query is None:
        if section:
            query = f'Generate wiki pages for the "{section}" section only'
        else:
            query = 'Generate wiki pages for the entire repository'
    asyncio.run(_wiki(project, query))


async def _wiki(project_id: Optional[str], query: str):
    """Wiki generation implementation."""
    try:
        if not project_id:
            project_id = _get_last_project()
            if not project_id:
                console.print("[yellow]No project specified. Use --project <id> or parse a repo first.[/yellow]")
                raise click.Abort()

        runtime = await ctx_obj.get_runtime()

        try:
            agent = runtime.agents.wiki_agent
        except AttributeError:
            console.print("[red]wiki_agent not found. Make sure it is registered in agents_service.py.[/red]")
            raise click.Abort()

        project_info = await runtime.projects.get(project_id)

        console.print(Panel.fit(
            f"[bold cyan]Project:[/bold cyan] {project_info.repo_name}\n"
            f"[bold cyan]Project ID:[/bold cyan] {project_id}\n"
            f"[bold cyan]Output:[/bold cyan] .qoder/repowiki/en/content/\n"
            f"[bold cyan]Query:[/bold cyan] {query}",
            title="📖 Wiki Generation",
            border_style="cyan"
        ))

        ctx = ChatContext(
            project_id=project_id,
            project_name=project_info.repo_name,
            curr_agent_id="wiki_agent",
            query=query,
            history=[],
            user_id=ctx_obj.default_user_id,
            conversation_id=f"wiki_{project_id}",
        )

        console.print("\n[bold green]🤖 Wiki Agent:[/bold green] generating...\n")

        pages_written = []
        async for chunk in agent.stream(ctx):
            if chunk.response:
                console.print(chunk.response, end="", markup=False)
                # track written pages from tool output lines
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
            console.print("[yellow]Wiki generation complete. Check .qoder/repowiki/en/content/ for output.[/yellow]")

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
        console.print(f"   potpie chat --agent <agent-id>")
        console.print(f"   potpie ask \"question\" --agent <agent-id>")
        
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
            console.print("Parse a repository first: potpie parse repo /path/to/repo")
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
        potpie projects remove <project-id>
        potpie projects remove <project-id> --force
    """
    asyncio.run(_remove_project(project_id, force))


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

# Default eval cases covering common codebase Q&A scenarios
_DEFAULT_EVAL_CASES = [
    {
        "name": "architecture overview",
        "question": "Explain the overall system architecture",
        "rubrics": [
            "Answer is specific to the actual codebase, not a generic description",
            "Answer mentions at least two concrete components, modules, or layers from the project",
        ],
    },
    {
        "name": "entry point",
        "question": "What is the main entry point of the application?",
        "rubrics": [
            "Answer identifies a specific file or function as the entry point",
            "Answer does not just say 'I don't know' or ask for clarification",
        ],
    },
    {
        "name": "data flow",
        "question": "How does data flow from an API request to the database?",
        "rubrics": [
            "Answer describes at least two steps in the data flow",
            "Answer references actual files, classes, or functions from the codebase",
        ],
    },
    {
        "name": "key dependencies",
        "question": "What are the main external libraries or frameworks used?",
        "rubrics": [
            "Answer lists at least two real dependencies from the project",
            "Answer does not hallucinate libraries not present in the project",
        ],
    },
]


@cli.command()
@click.option("--project", "-p", required=True, help="Project ID to evaluate against")
@click.option("--agent", "-a", default="codebase_qna_agent", show_default=True, help="Agent ID to evaluate")
@click.option("--cases", "-c", default=None, help="Path to YAML file with custom eval cases")
@click.option("--concurrency", default=1, show_default=True, help="Max concurrent evaluations")
def eval(project: str, agent: str, cases: Optional[str], concurrency: int):
    """
    🧪 Evaluate agent response quality using LLM-as-a-judge.

    Runs a set of Q&A cases against the agent and scores each answer
    using pydantic_evals LLMJudge rubrics.

    Examples:
        potpie eval -p <project-id>
        potpie eval -p <project-id> --cases my_cases.yaml
        potpie eval -p <project-id> --agent codebase_qna_agent --concurrency 2
    """
    asyncio.run(_eval(project, agent, cases, concurrency))


async def _eval(project_id: str, agent_id: str, cases_path: Optional[str], concurrency: int):
    """Run evaluation."""
    import yaml as _yaml
    from dataclasses import dataclass
    from pydantic_evals import Case, Dataset
    from pydantic_evals.evaluators import LLMJudge
    from pydantic_evals.evaluators.llm_as_a_judge import set_default_judge_model
    from app.modules.intelligence.provider.litellm_model import LiteLLMModel

    try:
        runtime = await ctx_obj.get_runtime()
        project_info = await runtime.projects.get(project_id)

        # Point the LLM judge at the same model we use for everything else
        import os
        judge_model_name = os.environ.get("CHAT_MODEL", "github_copilot/gpt-4o")
        set_default_judge_model(LiteLLMModel(judge_model_name))

        # Load cases
        if cases_path:
            with open(cases_path) as f:
                raw = _yaml.safe_load(f)
            eval_cases_data = raw.get("cases", raw) if isinstance(raw, dict) else raw
        else:
            eval_cases_data = _DEFAULT_EVAL_CASES

        # Build pydantic_evals Dataset
        @dataclass
        class EvalInputs:
            question: str

        cases_list = []
        for c in eval_cases_data:
            rubrics = c.get("rubrics", [c.get("rubric", "Answer is helpful and accurate")])
            cases_list.append(
                Case(
                    name=c.get("name", c["question"][:50]),
                    inputs=EvalInputs(question=c["question"]),
                    evaluators=tuple(LLMJudge(rubric=r) for r in rubrics),
                )
            )

        dataset: Dataset[EvalInputs, str, None] = Dataset(cases=cases_list)

        console.print(f"\n[bold cyan]🧪 Evaluating[/bold cyan] [green]{project_info.repo_name}[/green] "
                      f"with agent [yellow]{agent_id}[/yellow] — {len(cases_list)} cases\n")

        # Task function: call the agent and return the text response
        async def task(inputs: EvalInputs) -> str:
            try:
                agent_handle = getattr(runtime.agents, agent_id)
                ctx = ChatContext(
                    project_id=project_id,
                    project_name=project_info.repo_name,
                    curr_agent_id=agent_id,
                    query=inputs.question,
                    history=[],
                    user_id=ctx_obj.default_user_id,
                )
                response = await agent_handle.query(ctx)
                return response.response
            except Exception as e:
                return f"ERROR: {e}"

        report = await dataset.evaluate(task, max_concurrency=concurrency, progress=True)
        report.print(console=console, include_input=True)

        # Summary score
        averages = report.averages()
        if averages and averages.assertions is not None:
            score_pct = averages.assertions * 100
            color = "green" if score_pct >= 70 else "yellow" if score_pct >= 40 else "red"
            console.print(f"\n[bold]Overall pass rate: [{color}]{score_pct:.0f}%[/{color}][/bold]")

    except Exception as e:
        console.print(f"[bold red]Error:[/bold red] {e}")
        raise click.Abort()


# ============================================================================
# MAIN ENTRY POINT
# ============================================================================

if __name__ == "__main__":
    try:
        cli()
    except KeyboardInterrupt:
        console.print("\n[yellow]Interrupted by user[/yellow]")
        sys.exit(130)
