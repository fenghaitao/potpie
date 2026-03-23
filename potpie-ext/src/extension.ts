import * as vscode from 'vscode';
import * as path from 'path';
import { RepoTreeProvider, ProjectNode } from './repoTreeProvider';
import { ProjectEntry } from './cliManager';
import { state } from './state';
import { WikiTreeProvider } from './wikiTreeProvider';
import { SidebarChatProvider } from './sidebarChatProvider';
import { HistoryManager } from './historyManager';
import * as workspaceManager from './workspaceManager';
import * as repoManager from './repoManager';
import * as serviceManager from './serviceManager';
import * as cliManager from './cliManager';
import { DeepWikiGenerator } from './deepWikiGenerator';
import { WikiViewerProvider } from './wikiViewerProvider';
import { WikiEvaluator } from './wikiEvaluator';
import { saveRepoPath, lookupRepoPath } from './repoPathStore';

// ── Output channel (shared across modules) ────────────────────────────────────

let outputChannel: vscode.OutputChannel;

function log(msg: string): void {
  outputChannel.appendLine(msg);
  console.log(msg);
}

// ── Repo dir tracked for deactivate() ────────────────────────────────────────

let potpieRepoDir: string | undefined;

// ── Status bar item (persistent, shows workspace path) ───────────────────────

let workspaceStatusBar: vscode.StatusBarItem;

// ── Activation ────────────────────────────────────────────────────────────────

export function activate(context: vscode.ExtensionContext): void {
  outputChannel = vscode.window.createOutputChannel('Potpie');
  outputChannel.show(true);
  context.subscriptions.push(outputChannel);

  // Status bar — always visible, shows current workspace, click to change
  workspaceStatusBar = vscode.window.createStatusBarItem(
    vscode.StatusBarAlignment.Left,
    100,
  );
  workspaceStatusBar.command = 'potpie.showWorkspace';
  workspaceStatusBar.tooltip = 'Potpie workspace — click to view / change';
  updateWorkspaceStatusBar(context);
  context.subscriptions.push(workspaceStatusBar);

  // Inject the shared logger into all modules
  workspaceManager.setLogger(log);
  repoManager.setLogger(log);
  serviceManager.setLogger(log);
  cliManager.setLogger(log);

  log('[Potpie] Extension activating…');

  const treeProvider = new RepoTreeProvider(context);

  // ── Tree View ───────────────────────────────────────────────────────────────
  const treeView = vscode.window.createTreeView('potpie.repoTree', {
    treeDataProvider: treeProvider,
    showCollapseAll: true,
  });

  // ── Workspace guard ─────────────────────────────────────────────────────────

  /**
   * Ensure workspace is configured AND services are ready before any
   * user-triggered action.  If workspace is missing, runs the full setup
   * flow.  If services are still starting, informs the user and returns
   * false so the calling command aborts.
   */
  async function requireServices(): Promise<boolean> {
    if (!workspaceManager.getWorkspacePath(context)) {
      await initEnvironment(context, treeProvider);
      updateWorkspaceStatusBar(context);
    }
    const status = treeProvider.serviceStatus;
    if (status === 'starting' || status === 'idle') {
      vscode.window.showWarningMessage(
        'Potpie: Backend services are still starting up. Please wait a moment and try again.',
      );
      return false;
    }
    if (status === 'error') {
      vscode.window.showErrorMessage(
        'Potpie: Backend services failed to start. Use "Retry" in the Potpie panel or check the Output channel.',
      );
      return false;
    }
    return true;
  }

  // ── Commands ────────────────────────────────────────────────────────────────

  // Shared output channel for all wiki operations (declared here so all commands can use it)
  const wikiOutputChannel = vscode.window.createOutputChannel('Potpie: DeepWiki');
  context.subscriptions.push(wikiOutputChannel);

  // ── Sidebar webview providers ─────────────────────────────────────────────
  const wikiTreeProvider = new WikiTreeProvider();
  const wikiTreeView = vscode.window.createTreeView('potpie.wikiView', {
    treeDataProvider: wikiTreeProvider,
    showCollapseAll: true,
  });
  context.subscriptions.push(wikiTreeView);

  const historyManager = new HistoryManager();

  const chatSidebarProvider = new SidebarChatProvider(
    context.extensionUri,
    () => potpieRepoDir,
    () => state.currentProjectId,
    historyManager,
  );
  context.subscriptions.push(
    vscode.window.registerWebviewViewProvider(
      SidebarChatProvider.viewType, chatSidebarProvider,
      { webviewOptions: { retainContextWhenHidden: true } },
    ),
  );

  /**
   * Triggered when the user clicks "Parse New Repo" in the sidebar.
   * 1. Ask user to pick a local directory.
   * 2. Auto-detect its git branch; let user confirm or override.
   * 3. Run `parse repo` via the CLI with a progress notification.
   * 4. Refresh the tree when done.
   */
  const cmdParseNewRepo = vscode.commands.registerCommand(
    'potpie.parseNewRepo',
    async () => {
      if (!await requireServices()) { return; }
      if (!potpieRepoDir) {
        vscode.window.showErrorMessage('Potpie: repo dir not available.');
        return;
      }

      // Step 1 — pick a directory
      const uris = await vscode.window.showOpenDialog({
        canSelectFiles: false,
        canSelectFolders: true,
        canSelectMany: false,
        openLabel: 'Select repository to parse',
      });
      if (!uris || uris.length === 0) { return; }
      const repoPath = uris[0].fsPath;

      // Step 2 — detect branch, let user confirm / override
      const detectedBranch = cliManager.detectBranch(repoPath);
      const branch = await vscode.window.showInputBox({
        prompt: 'Branch name to parse (leave blank to auto-detect from repo)',
        value: detectedBranch ?? '',
        placeHolder: detectedBranch ?? 'main',
      });
      if (branch === undefined) { return; } // user cancelled

      // Step 3 — run parse with progress
      log(`[Potpie] Parsing: ${repoPath} @ ${branch || '(auto-detect)'}`);
      try {
        await vscode.window.withProgress(
          {
            location: vscode.ProgressLocation.Notification,
            title: `Potpie: building knowledge graph for "${repoPath.split('/').pop()}"…`,
            cancellable: false,
          },
          () => cliManager.parseRepo(
            potpieRepoDir!,
            repoPath,
            branch || undefined,
          ),
        );
        // Resolve the final branch name (same logic as cliManager.parseRepo)
        const resolvedBranch = branch || cliManager.detectBranch(repoPath) || 'main';
        const repoName = repoPath.split('/').pop() || repoPath;
        saveRepoPath(context, repoName, resolvedBranch, repoPath);
        log(`[Potpie] Saved repo path mapping: ${repoName}:${resolvedBranch} -> ${repoPath}`);
        vscode.window.showInformationMessage(
          `Potpie: parsing complete for "${repoName}".`,
        );
        treeProvider.refresh();
      } catch (err) {
        log(`[Potpie] Parse failed: ${err}`);
        vscode.window.showErrorMessage(`Potpie: parse failed — ${err}`);
      }
    },
  );

  /**
   * Called when a project node is clicked in the tree.
   * Stores the repo name, branch and project ID, then opens the panel.
   */
  const cmdSelectProject = vscode.commands.registerCommand(
    'potpie.selectProject',
    async (project: ProjectEntry) => {
      if (!await requireServices()) { return; }
      log(`[Potpie] Selected project: ${project.repo_name} [${project.branch_name}] (${project.id})`);
      state.currentRepo = project.repo_name;
      state.currentBranch = project.branch_name;
      state.currentProjectId = project.id;
      // Resolve repo_path: prefer the value from the CLI (stored in DB),
      // fall back to the local mapping saved when this repo was parsed.
      state.currentRepoPath =
        project.repo_path ||
        lookupRepoPath(context, project.repo_name, project.branch_name) ||
        undefined;

      vscode.window.setStatusBarMessage(
        `Potpie: ${project.repo_name} @ ${project.branch_name}`,
        4000,
      );

      // Notify sidebar views of the newly selected repo
      wikiTreeView.description = `${project.repo_name} — ${project.branch_name}`;
      chatSidebarProvider.notifyRepoChanged(project.repo_name, project.branch_name);

      // Emit wiki state — resolved from workspace-controlled dir (no repoPath needed).
      const workspacePath = workspaceManager.getWorkspacePath(context);
      const gen = new DeepWikiGenerator(wikiOutputChannel);
      if (workspacePath) {
        const contentDir = DeepWikiGenerator.contentDir(workspacePath, project.repo_name, project.branch_name);
        if (gen.wikiExists(contentDir)) {
          wikiTreeProvider.setState('ready', contentDir);
        } else {
          wikiTreeProvider.setState('missing');
        }
      } else {
        wikiTreeProvider.setState('no-repo');
      }
    },
  );

  /**
   * Remove a project via the Potpie CLI.
   * Called from the tree-item context menu (right-click → Remove Project).
   */
  const cmdRemoveProject = vscode.commands.registerCommand(
    'potpie.removeProject',
    async (node: ProjectNode) => {
      if (!await requireServices()) { return; }
      if (!potpieRepoDir) {
        vscode.window.showErrorMessage('Potpie: repo dir not available.');
        return;
      }
      const { id, repo_name, branch_name } = node.project;
      const confirm = await vscode.window.showWarningMessage(
        `Remove project "${repo_name} [${branch_name}]"? This deletes its knowledge graph.`,
        { modal: true },
        'Remove',
      );
      if (confirm !== 'Remove') { return; }
      try {
        await cliManager.removeProject(potpieRepoDir, id);
        log(`[Potpie] Project removed: ${id}`);
        treeProvider.refresh();
      } catch (err) {
        log(`[Potpie] Failed to remove project: ${err}`);
        vscode.window.showErrorMessage(`Potpie: failed to remove project — ${err}`);
      }
    },
  );

  /**
   * Focus the Potpie sidebar container.
   */
  const cmdOpenPanel = vscode.commands.registerCommand(
    'potpie.openPanel',
    async () => {
      await vscode.commands.executeCommand('workbench.view.extension.potpie-container');
    },
  );

  /**
   * Show the current workspace path and offer to change it.
   */
  const cmdShowWorkspace = vscode.commands.registerCommand(
    'potpie.showWorkspace',
    async () => {
      const current = workspaceManager.getWorkspacePath(context);
      const msg = current
        ? `Potpie workspace: ${current}`
        : 'Potpie workspace: (not configured)';
      const action = await vscode.window.showInformationMessage(
        msg,
        'Change Workspace',
        'Open Output',
      );
      if (action === 'Change Workspace') {
        await workspaceManager.clearWorkspacePath(context);
        treeProvider.setServiceStatus('idle');
        updateWorkspaceStatusBar(context);
        await initEnvironment(context, treeProvider);
        updateWorkspaceStatusBar(context);
      } else if (action === 'Open Output') {
        outputChannel.show(true);
      }
    },
  );

  /**
   * Allow the user to re-select the workspace directory.
   */
  const cmdSetWorkspace = vscode.commands.registerCommand(
    'potpie.setWorkspace',
    async () => {
      await workspaceManager.clearWorkspacePath(context);
      treeProvider.setServiceStatus('idle');
      updateWorkspaceStatusBar(context);
      await initEnvironment(context, treeProvider);
      updateWorkspaceStatusBar(context);
    },
  );

  /**
   * Retry starting backend services after a previous failure.
   */
  const cmdRetryServices = vscode.commands.registerCommand(
    'potpie.retryServices',
    async () => {
      await initEnvironment(context, treeProvider);
      updateWorkspaceStatusBar(context);
    },
  );

  // ── Wiki commands ──────────────────────────────────────────────────────────

  const wikiViewer = new WikiViewerProvider(context.extensionUri);
  context.subscriptions.push({ dispose: () => wikiViewer.dispose() });

  /**
   * Generate a DeepWiki for the currently selected project.
   * Uses the project's `repo_path` as both the target repo and the wiki
   * output root (wiki lands at `<repo_path>/.repowiki/en/content/`).
   */
  const cmdGenerateWiki = vscode.commands.registerCommand(
    'potpie.generateWiki',
    async () => {
      if (!await requireServices()) { return; }
      if (!potpieRepoDir) {
        vscode.window.showErrorMessage('Potpie: repo dir not available.');
        return;
      }

      if (!state.currentProjectId || !state.currentRepo) {
        vscode.window.showWarningMessage(
          'Potpie: select a project in the sidebar before generating its wiki.',
        );
        return;
      }

      const projectRepoPath = state.currentRepoPath;
      if (!projectRepoPath) {
        vscode.window.showErrorMessage(
          'Potpie: repo_path not available for the selected project. ' +
          'Try removing and re-parsing the project.',
        );
        return;
      }

      const workspacePath = workspaceManager.getWorkspacePath(context);
      if (!workspacePath) {
        vscode.window.showErrorMessage('Potpie: workspace not configured. Please set workspace first.');
        return;
      }
      const contentDir = DeepWikiGenerator.contentDir(workspacePath, state.currentRepo!, state.currentBranch!);
      const generator = new DeepWikiGenerator(wikiOutputChannel);

      wikiTreeProvider.setState('generating', contentDir);
      await vscode.window.withProgress(
        {
          location: vscode.ProgressLocation.Notification,
          title: `Potpie: generating DeepWiki for "${state.currentRepo}"…`,
          cancellable: true,
        },
        async (progress, token) => {
          try {
            await generator.generate(
              projectRepoPath,
              potpieRepoDir!,
              { report: (msg) => progress.report({ message: msg }) },
              token,
              contentDir,
            );
            saveRepoPath(context, state.currentRepo!, state.currentBranch!, projectRepoPath);
            // Refresh the wiki tree with the newly generated pages
            wikiTreeProvider.setState('ready', contentDir);
            vscode.window.showInformationMessage(
              `Potpie: DeepWiki generated for "${state.currentRepo}"!`,
            );
          } catch (err) {
            wikiTreeProvider.setState('missing');
            if (err instanceof Error && err.message === 'Generation cancelled') {
              vscode.window.showWarningMessage('Potpie: wiki generation cancelled.');
            } else {
              log(`[Potpie] Wiki generation failed: ${err}`);
              vscode.window.showErrorMessage(`Potpie: wiki generation failed — ${err}`);
            }
          }
        },
      );
    },
  );

  /**
   * Browse and open pages from the DeepWiki of the currently selected project.
   * Offers to generate the wiki first if it does not yet exist.
   */
  const cmdViewWiki = vscode.commands.registerCommand(
    'potpie.viewWiki',
    async () => {
      if (!await requireServices()) { return; }

      if (!state.currentProjectId || !state.currentRepo) {
        vscode.window.showWarningMessage(
          'Potpie: select a project in the sidebar first.',
        );
        return;
      }

      const workspacePath = workspaceManager.getWorkspacePath(context);
      if (!workspacePath) {
        vscode.window.showErrorMessage('Potpie: workspace not configured. Please set workspace first.');
        return;
      }
      const contentDir = DeepWikiGenerator.contentDir(workspacePath, state.currentRepo!, state.currentBranch!);
      const generator = new DeepWikiGenerator(wikiOutputChannel);

      if (!generator.wikiExists(contentDir)) {
        const action = await vscode.window.showInformationMessage(
          `No DeepWiki found for "${state.currentRepo}". Generate one now?`,
          'Generate',
          'Cancel',
        );
        if (action !== 'Generate') { return; }
        // Trigger the generate command (includes progress UI)
        await vscode.commands.executeCommand('potpie.generateWiki');
        return;
      }

      const pages = generator.getWikiPages(contentDir);
      if (pages.length === 0) {
        vscode.window.showWarningMessage('Potpie: wiki exists but contains no pages.');
        return;
      }

      await wikiViewer.pickAndOpen(pages);
    },
  );

  const cmdOpenWikiPage = vscode.commands.registerCommand(
    'potpie.openWikiPage',
    async (filePath: string) => {
      await wikiViewer.openWikiPage({ name: path.basename(filePath, '.md'), filePath });
    },
  );

  /**
   * Evaluate the wiki for the currently selected project using the
   * wiki-evaluator skill (.kiro/skills/wiki-evaluator/SKILL.md) and the
   * VS Code Language Model API.  No subprocess or CLI is spawned.
   */
  const cmdEvaluateWiki = vscode.commands.registerCommand(
    'potpie.evaluateWiki',
    async () => {
      if (!await requireServices()) { return; }

      if (!state.currentProjectId || !state.currentRepo || !state.currentBranch) {
        vscode.window.showWarningMessage(
          'Potpie: select a project in the sidebar before evaluating its wiki.',
        );
        return;
      }

      if (!potpieRepoDir) {
        vscode.window.showErrorMessage('Potpie: repo dir not available.');
        return;
      }

      const workspacePath = workspaceManager.getWorkspacePath(context);
      if (!workspacePath) {
        vscode.window.showErrorMessage('Potpie: workspace not configured. Please set workspace first.');
        return;
      }

      const contentDir = DeepWikiGenerator.contentDir(
        workspacePath, state.currentRepo!, state.currentBranch!,
      );
      const generator = new DeepWikiGenerator(wikiOutputChannel);

      if (!generator.wikiExists(contentDir)) {
        vscode.window.showWarningMessage(
          'Potpie: Wiki not found. Please generate the wiki first.',
        );
        return;
      }

      const outputPath = path.join(
        workspacePath, 'evaluations',
        `${state.currentRepo}_${state.currentBranch}`,
        'wiki_eval_score.md',
      );

      const evaluator = new WikiEvaluator(wikiOutputChannel);

      // Ask user to choose Mode A (reference docs) or Mode B (AI + graph)
      const referenceDocsDir = await WikiEvaluator.promptForReferenceDocsDir();
      if (referenceDocsDir === undefined) { return; }  // user cancelled

      log(`[Potpie] Starting wiki evaluation for ${state.currentRepo} [${state.currentBranch}]`);

      try {
        await vscode.window.withProgress(
          {
            location: vscode.ProgressLocation.Notification,
            title: `Potpie: evaluating wiki for "${state.currentRepo}"…`,
            cancellable: false,
          },
          async () => {
            await evaluator.evaluate({
              projectId: state.currentProjectId!,
              repoName: state.currentRepo!,
              branchName: state.currentBranch!,
              wikiDir: contentDir,
              potpieRepoDir: potpieRepoDir!,
              outputPath,
              referenceDocsDir: referenceDocsDir || undefined,
            });
          },
        );
        vscode.window.showInformationMessage(
          `Potpie: wiki evaluation complete. Report saved to:\n${outputPath}`,
        );
        log(`[Potpie] Wiki evaluation complete — report: ${outputPath}`);
      } catch (err) {
        log(`[Potpie] Wiki evaluation failed: ${err}`);
        vscode.window.showErrorMessage(`Potpie: wiki evaluation failed — ${err}`);
      }
    },
  );

  const cmdClearChat = vscode.commands.registerCommand(
    'potpie.clearChat',
    () => {
      const repo   = state.currentRepo;
      const branch = state.currentBranch;
      if (repo && branch) {
        chatSidebarProvider.clearHistory(repo, branch);
      } else {
        vscode.window.showWarningMessage('Potpie: no project selected — nothing to clear.');
      }
    },
  );

  context.subscriptions.push(
    treeView,
    cmdParseNewRepo,
    cmdSelectProject,
    cmdRemoveProject,
    cmdOpenPanel,
    cmdShowWorkspace,
    cmdSetWorkspace,
    cmdRetryServices,
    cmdGenerateWiki,
    cmdViewWiki,
    cmdOpenWikiPage,
    cmdEvaluateWiki,
    cmdClearChat,
  );

  log('[Potpie] Commands and views registered');

  // ── Async environment initialisation (non-blocking) ──────────────────────
  initEnvironment(context, treeProvider)
    .then(() => {
      updateWorkspaceStatusBar(context);
    })
    .catch((err) => log(`[Potpie] Environment initialisation error: ${err}`));
}

// ── Deactivation ─────────────────────────────────────────────────────────────

export async function deactivate(): Promise<void> {
  if (potpieRepoDir) {
    log('[Potpie] Stopping backend services before VS Code exit…');
    await serviceManager.stopServices(potpieRepoDir);
  }
  log('[Potpie] Extension deactivated');
}

// ── Status bar helper ─────────────────────────────────────────────────────────

function updateWorkspaceStatusBar(context: vscode.ExtensionContext): void {
  const p = workspaceManager.getWorkspacePath(context);
  if (p) {
    workspaceStatusBar.text = `$(folder) Potpie: ${p}`;
    workspaceStatusBar.backgroundColor = undefined;
  } else {
    workspaceStatusBar.text = `$(folder-opened) Potpie: (no workspace)`;
    workspaceStatusBar.backgroundColor = new vscode.ThemeColor(
      'statusBarItem.warningBackground',
    );
  }
  workspaceStatusBar.show();
}

// ── Environment boot sequence ─────────────────────────────────────────────────

/**
 * Full startup sequence:
 *   1. Ensure the workspace directory exists (prompt user on first run).
 *   2. Clone the Potpie repository if not already present.
 *   3. Start backend services.
 *
 * @param treeProvider  When supplied, service status is reported via
 *                      setServiceStatus() so the tree reflects progress.
 */
async function initEnvironment(
  context: vscode.ExtensionContext,
  treeProvider?: import('./repoTreeProvider').RepoTreeProvider,
): Promise<void> {
  // Step 1 — workspace
  const workspacePath = await workspaceManager.ensureWorkspace(context);
  if (!workspacePath) {
    log('[Potpie] Workspace not configured — skipping environment setup');
    return;
  }

  // Signal that services are now being set up
  treeProvider?.setServiceStatus('starting');

  // Step 2 — clone repository
  let repoDir: string;
  try {
    repoDir = await repoManager.ensurePotpieRepo(workspacePath);
    potpieRepoDir = repoDir;
  } catch (err) {
    log(`[Potpie] Repository clone failed: ${err}`);
    treeProvider?.setServiceStatus('error');
    vscode.window.showErrorMessage(
      `Potpie: failed to clone repository — ${err}`,
    );
    return;
  }

  // Step 3 — start services
  try {
    await serviceManager.startServices(repoDir);
    treeProvider?.setRepoDir(repoDir);   // tell tree provider where potpie CLI lives
    treeProvider?.setServiceStatus('ready');
    log('[Potpie] Backend services ready');
  } catch (err) {
    log(`[Potpie] Service startup failed: ${err}`);
    treeProvider?.setServiceStatus('error');
    vscode.window.showErrorMessage(
      `Potpie: failed to start backend services — ${err}`,
    );
  }
}
