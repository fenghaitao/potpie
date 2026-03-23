import * as fs from 'fs';
import * as path from 'path';
import * as vscode from 'vscode';

// ── Constants ─────────────────────────────────────────────────────────────────

export const WORKSPACE_PATH_KEY = 'potpie.workspacePath';

// Sub-directories that must exist inside the workspace
const REQUIRED_DIRS = ['repos'];

// ── Module-level logger reference (injected from extension.ts) ────────────────

let _log: (msg: string) => void = (msg) => console.log(msg);

export function setLogger(logger: (msg: string) => void): void {
  _log = logger;
}

// ── Public API ────────────────────────────────────────────────────────────────

/**
 * Return the workspace path stored in global state, or undefined if not yet
 * configured.
 */
export function getWorkspacePath(
  context: vscode.ExtensionContext,
): string | undefined {
  return context.globalState.get<string>(WORKSPACE_PATH_KEY);
}

/**
 * Ensure a valid workspace path is known.
 *
 * On first run (no path stored) this prompts the user to pick or type a
 * directory.  If the user types a path that does not exist they are offered
 * the choice to create it.
 * On subsequent runs the stored path is used directly.
 *
 * @returns The resolved workspace path, or undefined if the user cancelled.
 */
export async function ensureWorkspace(
  context: vscode.ExtensionContext,
): Promise<string | undefined> {
  const stored = getWorkspacePath(context);
  if (stored) {
    _log(`[Potpie] Workspace path loaded: ${stored}`);
    initWorkspaceLayout(stored);
    return stored;
  }

  // First-time setup — let the user choose how to specify the directory
  const method = await vscode.window.showQuickPick(
    [
      { label: '$(folder-opened) Browse for folder…', id: 'browse' },
      { label: '$(keyboard) Enter path manually',     id: 'type'   },
    ],
    {
      title: 'Potpie: Set Workspace Directory',
      placeHolder: 'How would you like to specify the workspace path?',
    },
  );

  if (!method) {
    vscode.window.showWarningMessage(
      'Potpie: No workspace directory selected. ' +
        'Some features will be unavailable until a workspace is configured.',
    );
    _log('[Potpie] Workspace selection cancelled by user');
    return undefined;
  }

  let workspacePath: string | undefined;

  if (method.id === 'browse') {
    // ── Folder picker (only existing directories) ──────────────────────────
    const picked = await vscode.window.showOpenDialog({
      canSelectFiles: false,
      canSelectFolders: true,
      canSelectMany: false,
      openLabel: 'Select Workspace',
      title:
        'Select a directory to use as the Potpie workspace. ' +
        'Make sure the disk has sufficient free space.',
    });

    if (!picked || picked.length === 0) {
      vscode.window.showWarningMessage(
        'Potpie: No workspace directory selected. ' +
          'Some features will be unavailable until a workspace is configured.',
      );
      _log('[Potpie] Workspace selection cancelled by user');
      return undefined;
    }

    workspacePath = picked[0].fsPath;
  } else {
    // ── Manual text entry ──────────────────────────────────────────────────
    const input = await vscode.window.showInputBox({
      title: 'Potpie: Set Workspace Directory',
      prompt: 'Enter the full path to use as the Potpie workspace.',
      placeHolder: '/path/to/workspace',
      validateInput: (value) => {
        const trimmed = value.trim();
        if (!trimmed) {
          return 'Path cannot be empty.';
        }
        if (!path.isAbsolute(trimmed)) {
          return 'Please enter an absolute path.';
        }
        return undefined;
      },
    });

    if (!input || !input.trim()) {
      vscode.window.showWarningMessage(
        'Potpie: No workspace directory specified. ' +
          'Some features will be unavailable until a workspace is configured.',
      );
      _log('[Potpie] Workspace input cancelled by user');
      return undefined;
    }

    workspacePath = input.trim();

    // If the path does not exist, offer to create it
    if (!fs.existsSync(workspacePath)) {
      const create = await vscode.window.showWarningMessage(
        `The path "${workspacePath}" does not exist. Create it?`,
        'Create',
        'Cancel',
      );
      if (create !== 'Create') {
        _log('[Potpie] User declined to create non-existent workspace path');
        return undefined;
      }
      try {
        fs.mkdirSync(workspacePath, { recursive: true });
        _log(`[Potpie] Created workspace directory: ${workspacePath}`);
      } catch (err) {
        vscode.window.showErrorMessage(
          `Potpie: Failed to create directory "${workspacePath}": ${err}`,
        );
        _log(`[Potpie] Failed to create workspace directory: ${err}`);
        return undefined;
      }
    }
  }

  await context.globalState.update(WORKSPACE_PATH_KEY, workspacePath);
  _log(`[Potpie] Workspace initialized at: ${workspacePath}`);
  vscode.window.showInformationMessage(
    `Potpie workspace set to: ${workspacePath}`,
  );

  initWorkspaceLayout(workspacePath);
  return workspacePath;
}

/**
 * Forget the stored workspace path (useful for "reset" commands in future).
 */
export async function clearWorkspacePath(
  context: vscode.ExtensionContext,
): Promise<void> {
  await context.globalState.update(WORKSPACE_PATH_KEY, undefined);
  _log('[Potpie] Workspace path cleared');
}

// ── Internal helpers ──────────────────────────────────────────────────────────

/**
 * Create the standard directory layout inside the workspace if it does not
 * already exist.
 */
function initWorkspaceLayout(workspacePath: string): void {
  for (const dir of REQUIRED_DIRS) {
    const fullPath = path.join(workspacePath, dir);
    if (!fs.existsSync(fullPath)) {
      fs.mkdirSync(fullPath, { recursive: true });
      _log(`[Potpie] Created directory: ${fullPath}`);
    }
  }
}
