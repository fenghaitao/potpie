/**
 * wikiEvaluator.ts
 *
 * Evaluates wiki quality using the wiki-evaluator skill via a generic agent loop.
 *
 * Architecture:
 *
 *   1. Load SKILL.md as the LLM's system-level instructions.
 *   2. Build a ToolRegistry with the `evaluate_wiki` tool.
 *      → The tool internally spawns the Python evaluation script.
 *      → The subprocess is a hidden implementation detail; the skill stays
 *        declarative and never mentions shell commands.
 *   3. Run the agent loop:
 *        LLM → JSON tool request → extension executes tool → result → LLM
 *        (repeat until LLM returns plain-text final answer)
 *   4. Write the LLM's final synthesis to the output file.
 *
 * Mode A (reference-docs-dir provided): CodeWikiBench rubric pipeline.
 * Mode B (no reference-docs-dir):       AI + code graph rubric pipeline.
 */
import * as fs from 'fs';
import * as path from 'path';
import * as vscode from 'vscode';
import { spawn } from 'child_process';
import { ToolRegistry } from './toolRegistry';
import { runAgentLoop } from './agentLoop';

// ── Public interface ──────────────────────────────────────────────────────────

export interface WikiEvaluateOptions {
  /** Potpie project ID (passed as --project-id). */
  projectId: string;
  /** Repository name (for display and logging). */
  repoName: string;
  /** Branch name (for display and logging). */
  branchName: string;
  /** Absolute path to the wiki content directory (--wiki-dir). */
  wikiDir: string;
  /** Absolute path of the cloned Potpie repo (.venv + skill files live here). */
  potpieRepoDir: string;
  /** Absolute path where the final synthesis report is written. */
  outputPath: string;
  /**
   * Optional reference-docs directory (Mode A).
   * When provided → Mode A (CodeWikiBench rubric pipeline).
   * When omitted  → Mode B (AI + graph rubrics).
   */
  referenceDocsDir?: string;
}

// ── WikiEvaluator ─────────────────────────────────────────────────────────────

export class WikiEvaluator {
  private static readonly SKILL_REL_PATH = path.join(
    '.kiro', 'skills', 'wiki-evaluator', 'SKILL.md',
  );
  private static readonly SCRIPT_REL_PATH = path.join(
    '.kiro', 'skills', 'wiki-evaluator', 'scripts', 'evaluate_wiki.py',
  );

  constructor(private readonly _outputChannel: vscode.OutputChannel) {}

  // ── Mode picker ───────────────────────────────────────────────────────────

  /**
   * Ask the user whether to use Mode A (reference docs) or Mode B (AI + graph).
   *
   * Returns:
   *   - non-empty string → Mode A, value is the chosen reference-docs path
   *   - empty string     → Mode B
   *   - undefined        → user cancelled
   */
  static async promptForReferenceDocsDir(): Promise<string | undefined> {
    const pick = await vscode.window.showQuickPick(
      [
        {
          label: '$(folder-opened)  Mode A — Reference Docs',
          description: 'Rubrics from a reference-docs directory (CodeWikiBench pipeline)',
          id: 'modeA',
        },
        {
          label: '$(graph)  Mode B — AI + Code Graph',
          description: 'Rubrics from AI + potpie code knowledge graph (default)',
          id: 'modeB',
        },
      ],
      {
        title: 'Potpie Wiki Evaluation — Choose Evaluation Mode',
        placeHolder: 'Select how rubrics should be generated',
      },
    );

    if (!pick) { return undefined; }

    if (pick.id === 'modeB') { return ''; }

    const uris = await vscode.window.showOpenDialog({
      title: 'Select Reference-Docs Directory',
      canSelectFolders: true,
      canSelectFiles: false,
      canSelectMany: false,
      openLabel: 'Use as Reference Docs',
    });

    if (!uris || uris.length === 0) { return undefined; }
    return uris[0].fsPath;
  }

  // ── Public API ────────────────────────────────────────────────────────────

  /**
   * Run the wiki evaluation via the agent loop.
   *
   * @throws if the skill file is missing, no LLM model is available, or a
   *         tool execution error is unrecoverable.
   */
  async evaluate(opts: WikiEvaluateOptions): Promise<void> {
    const ch = this._outputChannel;
    ch.show();
    ch.appendLine('');
    ch.appendLine('=== Wiki Evaluation (Agent Loop) ===');
    ch.appendLine(`Project:    ${opts.repoName} [${opts.branchName}]`);
    ch.appendLine(`Project ID: ${opts.projectId}`);
    ch.appendLine(`Wiki dir:   ${opts.wikiDir}`);
    ch.appendLine(`Mode:       ${opts.referenceDocsDir ? 'A (Reference Docs)' : 'B (AI + Graph)'}`);
    if (opts.referenceDocsDir) {
      ch.appendLine(`Ref docs:   ${opts.referenceDocsDir}`);
    }
    ch.appendLine(`Output:     ${opts.outputPath}`);

    // ── Step 1: Load skill definition ────────────────────────────────────────
    const skillPath = path.join(opts.potpieRepoDir, WikiEvaluator.SKILL_REL_PATH);
    ch.appendLine(`\nLoading skill: ${skillPath}`);

    let skillContent: string;
    try {
      skillContent = await fs.promises.readFile(skillPath, 'utf8');
    } catch (err) {
      throw new Error(
        `Wiki-evaluator skill not found at "${skillPath}". ` +
        `Ensure the Potpie repo has the .kiro/skills/wiki-evaluator/ directory.`,
      );
    }
    ch.appendLine('Skill loaded successfully.');

    // ── Step 2: Build tool registry ───────────────────────────────────────────
    const registry = new ToolRegistry();
    registry.registerTool('evaluate_wiki', {
      description: 'Run the full wiki evaluation pipeline and return its output',
      requiredParams: ['project_id', 'wiki_dir', 'output'],
      // The subprocess is hidden inside this handler — the skill never sees it.
      handler: (params) => this._runEvaluationScript(opts.potpieRepoDir, params),
    });

    // ── Step 3: Build initial messages ────────────────────────────────────────
    // The tool format instructions + registered tool list are injected
    // automatically by runAgentLoop() — no need to repeat them here.
    const systemInstructions = [
      skillContent,
      '',
      'After receiving a tool result, return a plain-text evaluation summary',
      '(NOT JSON). Include: overall score, pass/fail status, per-category',
      'breakdown, and key strengths / weaknesses.',
    ].join('\n');

    const userTask = this._buildTaskMessage(opts);

    const messages: vscode.LanguageModelChatMessage[] = [
      vscode.LanguageModelChatMessage.User(systemInstructions),
      vscode.LanguageModelChatMessage.User(userTask),
    ];

    // ── Step 4: Run agent loop ────────────────────────────────────────────────
    ch.appendLine('\n--- Agent Output ---');
    const finalAnswer = await runAgentLoop({ messages, tools: registry, outputChannel: ch });
    ch.appendLine('--- End of Agent Output ---');

    // ── Step 5: Write synthesis report ────────────────────────────────────────
    await fs.promises.mkdir(path.dirname(opts.outputPath), { recursive: true });
    await fs.promises.writeFile(opts.outputPath, finalAnswer, 'utf8');
    ch.appendLine(`\nSynthesis report written to: ${opts.outputPath}`);
  }

  // ── Private helpers ───────────────────────────────────────────────────────

  private _buildTaskMessage(opts: WikiEvaluateOptions): string {
    const modeNote = opts.referenceDocsDir
      ? `Mode A (Reference Docs rubrics). Reference docs: ${opts.referenceDocsDir}`
      : 'Mode B (AI + Code Graph rubrics — no reference docs).';

    return [
      `Please evaluate the wiki for the following project using ${modeNote}`,
      ``,
      `Inputs:`,
      `  project_id:  ${opts.projectId}`,
      `  wiki_dir:    ${opts.wikiDir}`,
      `  output:      ${opts.outputPath}`,
      opts.referenceDocsDir ? `  reference_docs_dir: ${opts.referenceDocsDir}` : '',
      ``,
      `Use the evaluate_wiki tool to run the evaluation, then provide a`,
      `concise plain-text summary of the results.`,
    ].filter(Boolean).join('\n');
  }

  /**
   * Run evaluate_wiki.py as a subprocess.
   * Private — only reachable through the tool registry (never called directly).
   */
  private _runEvaluationScript(
    potpieRepoDir: string,
    params: Record<string, unknown>,
  ): Promise<string> {
    const python = path.join(potpieRepoDir, '.venv', 'bin', 'python3');
    const scriptPath = path.join(potpieRepoDir, WikiEvaluator.SCRIPT_REL_PATH);

    const args: string[] = [
      scriptPath,
      '--project-id', String(params.project_id),
      '--wiki-dir',   String(params.wiki_dir),
      '--output',     String(params.output),
    ];
    if (params.reference_docs_dir) {
      args.push('--reference-docs-dir', String(params.reference_docs_dir));
    }

    const ch = this._outputChannel;
    ch.appendLine(
      `\n[Tool: evaluate_wiki] Command:\n  ` +
      [python, ...args].map((p) => p.includes(' ') ? `"${p}"` : p).join(' ') +
      '\n---',
    );

    return new Promise<string>((resolve, reject) => {
      const proc = spawn(python, args, {
        cwd: potpieRepoDir,
        env: { ...process.env },
      });

      let output = '';
      proc.stdout?.on('data', (d: Buffer) => { const s = d.toString(); output += s; ch.append(s); });
      proc.stderr?.on('data', (d: Buffer) => { const s = d.toString(); output += s; ch.append(s); });

      proc.on('close', (code: number | null) => {
        ch.appendLine('---');
        if (code === 0) {
          ch.appendLine('[Tool: evaluate_wiki] Script completed successfully.');
          resolve(output || 'Evaluation pipeline completed.');
        } else {
          // Resolve (not reject) so the LLM receives error context and can
          // report it gracefully rather than crashing the agent loop.
          resolve(`Script exited with code ${code}:\n${output}`);
        }
      });

      proc.on('error', (err: Error) => {
        reject(new Error(`Failed to spawn evaluation process: ${err.message}`));
      });
    });
  }
}
