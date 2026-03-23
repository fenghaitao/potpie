import * as vscode from 'vscode';
import * as workspaceManager from './workspaceManager';
import * as cliManager from './cliManager';
import { ProjectEntry } from './cliManager';

export type ServiceStatus = 'idle' | 'starting' | 'ready' | 'error';

// ── Tree node ──────────────────────────────────────────────────────────────────

/**
 * A single project entry in the tree — represents one (repo, branch) pair
 * with its associated Potpie project ID.
 *
 * Label format:  <repo-name> [<branch>]
 * Description:   <project-id>   (shown dimmed to the right)
 */
export class ProjectNode extends vscode.TreeItem {
  constructor(public readonly project: ProjectEntry) {
    const branchLabel = project.branch_name || '(unknown)';
    super(
      `${project.repo_name} [${branchLabel}]`,
      vscode.TreeItemCollapsibleState.None,
    );

    this.description = project.id;
    this.tooltip =
      `Repo: ${project.repo_name}\n` +
      `Branch: ${branchLabel}\n` +
      `Project ID: ${project.id}\n` +
      `Status: ${project.status}`;
    this.contextValue = 'potpie-project';
    this.iconPath = new vscode.ThemeIcon(
      project.status === 'READY' ? 'repo' : 'repo-forked',
    );
    this.command = {
      command: 'potpie.selectProject',
      title: 'Select Project',
      arguments: [project],
    };
  }
}

// ── Tree data provider ────────────────────────────────────────────────────────

export class RepoTreeProvider
  implements vscode.TreeDataProvider<vscode.TreeItem>
{
  private _serviceStatus: ServiceStatus = 'idle';
  private _repoDir: string | undefined;

  constructor(private readonly context: vscode.ExtensionContext) {}

  // ── Setters ─────────────────────────────────────────────────────────────────

  get serviceStatus(): ServiceStatus {
    return this._serviceStatus;
  }

  setServiceStatus(status: ServiceStatus): void {
    this._serviceStatus = status;
    this.refresh();
  }

  /** Called once the Potpie repo has been cloned / located. */
  setRepoDir(repoDir: string): void {
    this._repoDir = repoDir;
    this.refresh();
  }

  // ── TreeDataProvider ────────────────────────────────────────────────────────

  private readonly _onDidChangeTreeData = new vscode.EventEmitter<
    vscode.TreeItem | undefined | null | void
  >();

  readonly onDidChangeTreeData: vscode.Event<
    vscode.TreeItem | undefined | null | void
  > = this._onDidChangeTreeData.event;

  /** Force a full tree refresh (e.g. after a project is removed or added). */
  refresh(): void {
    this._onDidChangeTreeData.fire();
  }

  getTreeItem(element: vscode.TreeItem): vscode.TreeItem {
    return element;
  }

  async getChildren(
    element?: vscode.TreeItem,
  ): Promise<vscode.TreeItem[]> {
    // ProjectNodes are leaf nodes — they have no children.
    if (element) {
      return [];
    }

    // ── No workspace configured yet ─────────────────────────────────────────
    if (!workspaceManager.getWorkspacePath(this.context)) {
      const node = new vscode.TreeItem(
        'Click to configure Potpie workspace\u2026',
        vscode.TreeItemCollapsibleState.None,
      );
      node.iconPath = new vscode.ThemeIcon('warning');
      node.tooltip = 'Workspace not configured \u2014 click to set it up';
      node.command = { command: 'potpie.setWorkspace', title: 'Configure Workspace' };
      return [node];
    }

    // ── Services still starting ─────────────────────────────────────────────
    if (this._serviceStatus === 'idle' || this._serviceStatus === 'starting') {
      const node = new vscode.TreeItem(
        'Starting Potpie services\u2026 (this may take a while)',
        vscode.TreeItemCollapsibleState.None,
      );
      node.iconPath = new vscode.ThemeIcon('loading~spin');
      node.tooltip = 'Backend services are being set up. Please wait.';
      return [node];
    }

    // ── Service startup failed ───────────────────────────────────────────────
    if (this._serviceStatus === 'error') {
      const node = new vscode.TreeItem(
        'Failed to start services \u2014 click to retry',
        vscode.TreeItemCollapsibleState.None,
      );
      node.iconPath = new vscode.ThemeIcon('error');
      node.tooltip = 'Backend services failed to start. Click to retry.';
      node.command = { command: 'potpie.retryServices', title: 'Retry Services' };
      return [node];
    }

    // ── Services ready: load project list from CLI ───────────────────────────
    if (!this._repoDir) {
      return [];
    }

    try {
      const projects = await cliManager.listProjects(this._repoDir);
      // Returning [] lets the viewsWelcome content take over.
      if (projects.length === 0) {
        return [];
      }
      return projects.map((p) => new ProjectNode(p));
    } catch (err) {
      vscode.window.showErrorMessage(
        `Potpie: failed to list projects — ${err}`,
      );
      return [];
    }
  }
}
