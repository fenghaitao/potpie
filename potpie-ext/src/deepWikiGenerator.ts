/**
 * deepWikiGenerator.ts
 *
 * Generates DeepWiki documentation for a project by delegating to
 * `potpie_cli.py deepwiki-open-wiki -r <repoPath> --output-dir <contentDir>`.
 *
 * Wiki files are written to a workspace-controlled location:
 *   <workspacePath>/wikis/<repoName>_<branchName>/en/content/
 *
 * This makes wiki existence checkable purely from project metadata (repoName +
 * branchName), without needing to know the local repo path.  Only wiki
 * *generation* still requires the local repo path (passed via -r flag).
 */
import * as vscode from 'vscode';
import * as fs from 'fs';
import * as path from 'path';
import { spawn } from 'child_process';

// ── Public types ──────────────────────────────────────────────────────────────

export interface WikiPage {
  /** Display name, e.g. "architecture/overview" */
  name: string;
  /** Absolute path to the .md file. */
  filePath: string;
}

export interface GenerationProgress {
  report(message: string): void;
}

// ── Generator class ───────────────────────────────────────────────────────────

export class DeepWikiGenerator {
  private _currentProcess: ReturnType<typeof exec> | undefined;

  constructor(private readonly _outputChannel: vscode.OutputChannel) {}

  // ── Static helpers ────────────────────────────────────────────────────────

  /**
   * Compute the workspace-controlled wiki content directory for a project.
   *
   * Path: <workspacePath>/wikis/<repoName>_<branchName>/en/content/
   *
   * This is deterministic from project metadata alone — no local repo path
   * needed — so wiki existence survives VS Code restarts without re-resolving
   * the repo path.
   */
  static contentDir(
    workspacePath: string,
    repoName: string,
    branchName: string,
  ): string {
    return path.join(workspacePath, 'wikis', `${repoName}_${branchName}`, 'en', 'content');
  }

  // ── Public API ──────────────────────────────────────────────────────────────

  /**
   * Generate the DeepWiki documentation for `repoPath`, writing output to
   * `contentDir`.
   *
   * @param repoPath   The repository to document (target git repo).
   * @param repoDir    The cloned Potpie repo dir (must contain .venv + potpie_cli.py).
   * @param progress   Progress reporter for UI feedback.
   * @param cancellationToken  Token that kills the subprocess when fired.
   * @param contentDir Absolute path where wiki .md files should be written.
   */
  async generate(
    repoPath: string,
    repoDir: string,
    progress: GenerationProgress,
    cancellationToken: vscode.CancellationToken,
    contentDir: string,
  ): Promise<void> {
    this._outputChannel.show();

    let cancelled = false;
    cancellationToken.onCancellationRequested(() => {
      cancelled = true;
      this._currentProcess?.kill();
    });

    progress.report('Starting DeepWiki generation…');
    this._outputChannel.appendLine('\n=== DeepWiki generation ===');
    this._outputChannel.appendLine(`Repository:  ${repoPath}`);
    this._outputChannel.appendLine(`Potpie dir:  ${repoDir}`);
    this._outputChannel.appendLine(`Wiki output: ${contentDir}`);

    await this._runCli(repoPath, repoDir, cancellationToken, contentDir);

    if (cancelled) {
      throw new Error('Generation cancelled');
    }
  }

  /**
   * Returns true when `contentDir` exists and contains at least one Markdown
   * file (directly or in a sub-directory).
   */
  wikiExists(contentDir: string): boolean {
    if (!fs.existsSync(contentDir)) { return false; }
    return this._hasMarkdown(contentDir);
  }

  /**
   * Recursively list all `.md` files under `contentDir`, sorted
   * alphabetically by display name.
   */
  getWikiPages(contentDir: string): WikiPage[] {
    const pages: WikiPage[] = [];
    this._scan(contentDir, '', pages);
    return pages.sort((a, b) => a.name.localeCompare(b.name));
  }

  // ── Private helpers ─────────────────────────────────────────────────────────

  private _hasMarkdown(dir: string): boolean {
    for (const entry of fs.readdirSync(dir)) {
      if (entry.endsWith('.md')) { return true; }
      const full = path.join(dir, entry);
      if (fs.statSync(full).isDirectory() && this._hasMarkdown(full)) {
        return true;
      }
    }
    return false;
  }

  private _scan(dir: string, prefix: string, pages: WikiPage[]): void {
    if (!fs.existsSync(dir)) { return; }
    for (const entry of fs.readdirSync(dir)) {
      const full = path.join(dir, entry);
      if (fs.statSync(full).isDirectory()) {
        this._scan(full, prefix ? `${prefix}/${entry}` : entry, pages);
      } else if (entry.endsWith('.md')) {
        const name = (prefix ? `${prefix}/` : '') + entry.replace(/\.md$/, '');
        pages.push({ name, filePath: full });
      }
    }
  }

  /**
   * Spawn:
   *   <repoDir>/.venv/bin/python3 potpie_cli.py deepwiki-open-wiki \
   *     -r <repoPath> --output-dir <contentDir>
   *
   * The CLI sets POTPIE_WIKI_OUTPUT_DIR=<contentDir> before running the agent,
   * so all wiki pages are written to that directory.
   */
  private _runCli(
    repoPath: string,
    repoDir: string,
    cancellationToken: vscode.CancellationToken,
    contentDir: string,
  ): Promise<void> {
    const python = path.join(repoDir, '.venv', 'bin', 'python3');
    const cli    = path.join(repoDir, 'potpie_cli.py');
    const args   = [cli, 'deepwiki-open-wiki', '-r', repoPath, '--output-dir', contentDir];

    const commandForLogging = [python, ...args].map((part) =>
      part.includes(' ') ? `"${part}"` : part,
    ).join(' ');
    this._outputChannel.appendLine(`\nCommand: ${commandForLogging}\n---`);

    return new Promise<void>((resolve, reject) => {
      this._currentProcess = spawn(python, args, {
        cwd: repoPath,
        env: { ...process.env },
      });

      this._currentProcess.stdout?.on('data', (data: string | Buffer) => {
        this._outputChannel.append(data.toString());
      });
      this._currentProcess.stderr?.on('data', (data: string | Buffer) => {
        this._outputChannel.append(data.toString());
      });

      cancellationToken.onCancellationRequested(() => {
        this._currentProcess?.kill();
      });

      this._currentProcess.on('close', (code: number | null) => {
        this._outputChannel.appendLine('---');
        if (code === 0) {
          this._outputChannel.appendLine('✓ DeepWiki generation completed successfully');
          resolve();
        } else {
          // Treat partial output as a soft success
          if (this.wikiExists(contentDir)) {
            this._outputChannel.appendLine(
              `⚠ Generation exited with code ${code} (partial results available)`,
            );
            resolve();
          } else {
            reject(new Error(`DeepWiki generation failed with exit code ${code}`));
          }
        }
      });

      this._currentProcess.on('error', (err: Error) => {
        reject(new Error(`Failed to start CLI: ${err.message}`));
      });
    });
  }
}
