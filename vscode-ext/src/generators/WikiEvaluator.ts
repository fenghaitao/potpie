import * as vscode from 'vscode';
import * as fs from 'fs';
import * as path from 'path';
import { exec } from 'child_process';
import { promisify } from 'util';
import { UvManager } from '../utils/uvManager';

const execAsync = promisify(exec);

const SKILLS_REPO_URL = 'https://github.com/intel-sandbox/simics-skills.git';
const SKILLS_REPO_DIR = '.tmp_repos/simics-skills-repo';
const EVALUATOR_SUBPATH = path.join('skills', 'wiki-evaluator');

interface EvaluationParams {
	/** Absolute path to the repository directory (passed as --repo-dir) */
	repoDir: string;
	/** Evaluation mode: auto | single-wiki | multi-wiki */
	mode: string;
	/** Optional wiki folder name or path (passed as --wiki-dir, single-wiki only) */
	wikiDir?: string;
	/** Which wiki to evaluate in multi-wiki mode: codewiki | deepwiki | all */
	targetWiki?: string;
}

/**
 * Wiki Evaluator: evaluates generated wiki/documentation quality using the
 * intel-sandbox/simics-skills wiki-evaluator skill.
 *
 *  Flow:
 *  1. Clone / reuse .tmp_simics-skills-repo in the workspace root
 *  2. Run  `uv sync`  in the evaluator base directory
 *  3. Prompt the user for parameters (repo-name, workdir, mode, …)
 *  4. Execute the evaluation and stream the output to the Wiki Evaluator panel
 */
export class WikiEvaluator {
	private outputChannel: vscode.OutputChannel;
	private currentProcess: ReturnType<typeof exec> | undefined;

	constructor() {
		this.outputChannel = vscode.window.createOutputChannel('Wiki Evaluator');
	}

	// -----------------------------------------------------------------------
	// Public entry point
	// -----------------------------------------------------------------------

	async evaluate(workspaceRoot: string): Promise<void> {
		this.outputChannel.show(true);
		this.outputChannel.appendLine('');
		this.outputChannel.appendLine('╔══════════════════════════════════════╗');
		this.outputChannel.appendLine('║         Wiki Evaluator               ║');
		this.outputChannel.appendLine('╚══════════════════════════════════════╝');
		this.outputChannel.appendLine('');

		try {
			// Step 1 – download tool
			const skillsRepoPath = await this.downloadTool(workspaceRoot);

			// Step 2 – setup uv environment
			const evaluatorBaseDir = path.join(skillsRepoPath, EVALUATOR_SUBPATH);
			await this.setupEnvironment(evaluatorBaseDir);

			// Step 3 – collect user inputs
			const params = await this.collectInputs(workspaceRoot);
			if (!params) {
				this.outputChannel.appendLine('⚠ Evaluation cancelled by user.');
				return;
			}

			// Step 4 – run evaluation
			await this.runEvaluation(evaluatorBaseDir, params);

		} catch (error) {
			const message = error instanceof Error ? error.message : String(error);
			this.outputChannel.appendLine('');
			this.outputChannel.appendLine(`✗ Evaluation failed: ${message}`);
			vscode.window.showErrorMessage(`Wiki evaluation failed: ${message}`);
		}
	}

	// -----------------------------------------------------------------------
	// Step 1: Download / reuse the simics-skills repository
	// -----------------------------------------------------------------------

	private async downloadTool(workspaceRoot: string): Promise<string> {
		const skillsRepoPath = path.join(workspaceRoot, SKILLS_REPO_DIR);

		if (fs.existsSync(skillsRepoPath)) {
			this.outputChannel.appendLine(`ℹ  Using existing skills repository: ${skillsRepoPath}`);
			this.outputChannel.appendLine('   (Delete .tmp_repos/simics-skills-repo to force a fresh clone)');
			this.outputChannel.appendLine('');
			return skillsRepoPath;
		}

		this.outputChannel.appendLine('=== Step 1: Cloning simics-skills repository ===');
		this.outputChannel.appendLine(`URL : ${SKILLS_REPO_URL}`);
		this.outputChannel.appendLine(`Dest: ${skillsRepoPath}`);

		try {
			fs.mkdirSync(path.dirname(skillsRepoPath), { recursive: true });
			const { stdout, stderr } = await execAsync(
				`git clone --depth 1 "${SKILLS_REPO_URL}" "${SKILLS_REPO_DIR}"`,
				{ cwd: workspaceRoot }
			);
			if (stdout) this.outputChannel.appendLine(stdout);
			if (stderr) this.outputChannel.appendLine(stderr);

			this.outputChannel.appendLine('✓ Repository cloned successfully');
			this.outputChannel.appendLine('');
			return skillsRepoPath;
		} catch (error) {
			throw new Error(`Failed to clone simics-skills: ${error instanceof Error ? error.message : String(error)}`);
		}
	}

	// -----------------------------------------------------------------------
	// Step 2: Set up the uv virtual environment
	// -----------------------------------------------------------------------

	private async setupEnvironment(evaluatorBaseDir: string): Promise<void> {
		this.outputChannel.appendLine('=== Step 2: Setting up uv environment ===');
		this.outputChannel.appendLine(`Base dir: ${evaluatorBaseDir}`);

		await UvManager.ensureInstalled(this.outputChannel);
		await UvManager.sync(evaluatorBaseDir, this.outputChannel);

		this.outputChannel.appendLine('');
	}

	// -----------------------------------------------------------------------
	// Step 3: Collect user inputs
	// -----------------------------------------------------------------------

	private async collectInputs(workspaceRoot: string): Promise<EvaluationParams | undefined> {
		this.outputChannel.appendLine('=== Step 3: Collecting evaluation parameters ===');

		// ── repo-dir ───────────────────────────────────────────────────────
		// Default to the current workspace root which usually IS the repo.
		const repoDir = await vscode.window.showInputBox({
			title: 'Wiki Evaluator – Step 1 of 3: Repository directory',
			prompt: 'Absolute path to the repository directory (passed as --repo-dir)',
			value: workspaceRoot,
			ignoreFocusOut: true,
			validateInput: (v) => {
				if (!v.trim()) return 'Repository directory is required';
				if (!path.isAbsolute(v)) return 'Please enter an absolute path';
				return null;
			}
		});
		if (!repoDir) return undefined;

		// ── mode ───────────────────────────────────────────────────────────
		const modeChoice = await vscode.window.showQuickPick(
			[
				{
					label: '$(symbol-misc) auto',
					description: 'Auto-detect based on directory structure (recommended)',
					mode: 'auto'
				},
				{
					label: '$(file-code) single-wiki',
					description: 'Evaluate one wiki source (.codewiki / custom folder)',
					mode: 'single-wiki'
				},
				{
					label: '$(files) multi-wiki',
					description: 'Compare .codewiki vs .deepwiki side-by-side',
					mode: 'multi-wiki'
				}
			],
			{
				title: 'Wiki Evaluator – Step 2 of 3: Evaluation mode',
				placeHolder: 'Select evaluation mode'
			}
		);
		if (!modeChoice) return undefined;
		const mode = modeChoice.mode;

		// ── wiki-dir (single-wiki only, optional) ─────────────────────────
		// Leave blank to let the evaluator auto-detect .codewiki/.deepwiki.
		let wikiDir: string | undefined;
		if (mode === 'single-wiki') {
			const wikiDirInput = await vscode.window.showInputBox({
				title: 'Wiki Evaluator – Step 3 of 3: Wiki folder (optional)',
				prompt: 'Folder name or path for the wiki (leave blank to auto-detect .codewiki/.deepwiki)',
				value: '',
				placeHolder: 'e.g. .codewiki  or  /abs/path/to/wiki  (blank = auto)',
				ignoreFocusOut: true
			});
			if (wikiDirInput === undefined) return undefined; // Escape pressed
			wikiDir = wikiDirInput.trim() || undefined;
		}

		// ── target-wiki (multi-wiki / auto only) ──────────────────────────
		// When both wikis exist the user picks which one to score (or both).
		let targetWiki: string | undefined;
		if (mode === 'multi-wiki' || mode === 'auto') {
			const targetChoice = await vscode.window.showQuickPick(
				[
					{
						label: '$(file-code) CodeWiki  (.codewiki)',
						description: 'Evaluate only the CodeWiki output (default)',
						target: 'codewiki'
					},
					{
						label: '$(book) DeepWiki  (.deepwiki)',
						description: 'Evaluate only the DeepWiki output',
						target: 'deepwiki'
					},
					{
						label: '$(files) All wikis',
						description: 'Evaluate both CodeWiki and DeepWiki and compare',
						target: 'all'
					}
				],
				{
					title: 'Wiki Evaluator – Step 3 of 3: Target wiki',
					placeHolder: 'Which wiki should be the evaluation target?'
				}
			);
			if (!targetChoice) return undefined;
			targetWiki = targetChoice.target;
		}

		this.outputChannel.appendLine(`  repo-dir  : ${repoDir}`);
		this.outputChannel.appendLine(`  mode      : ${mode}`);
		if (wikiDir) {
			this.outputChannel.appendLine(`  wiki-dir  : ${wikiDir}`);
		}
		if (targetWiki) {
			this.outputChannel.appendLine(`  target    : ${targetWiki}`);
		}
		this.outputChannel.appendLine('');

		return { repoDir, mode, wikiDir, targetWiki };
	}

	// -----------------------------------------------------------------------
	// Step 4: Run the evaluation and stream output
	// -----------------------------------------------------------------------

	private async runEvaluation(evaluatorBaseDir: string, params: EvaluationParams): Promise<void> {
		this.outputChannel.appendLine('=== Step 4: Running Wiki Evaluator ===');

		// Build the command
		const args: string[] = [
			`uv run --directory "${evaluatorBaseDir}" wiki-evaluator`,
			`--repo-dir "${params.repoDir}"`,
			`--mode ${params.mode}`
		];

		// --wiki-dir is optional; omit when not provided so auto-detection kicks in
		if (params.wikiDir) {
			args.push(`--wiki-dir "${params.wikiDir}"`);
		}

		// --target-wiki selects which wiki to score in multi-wiki / auto mode
		if (params.targetWiki) {
			args.push(`--target-wiki ${params.targetWiki}`);
		}

		// --code-based-rubrics enabled by default
		args.push('--code-based-rubrics');

		// Exclude tool repos cloned under .tmp_repos from code-based evaluation
		args.push('--exclude ".tmp_repos"');

		const command = args.join(' \\\n  ');

		this.outputChannel.appendLine('Command:');
		this.outputChannel.appendLine(command);
		this.outputChannel.appendLine('---');

		await vscode.window.withProgress(
			{
				location: vscode.ProgressLocation.Notification,
				title: 'Running Wiki Evaluator…',
				cancellable: true
			},
			async (_progress, token) => {
				await new Promise<void>((resolve, reject) => {
					this.currentProcess = exec(command, {
						cwd: evaluatorBaseDir,
						shell: '/bin/bash',
						maxBuffer: 20 * 1024 * 1024
					});

					token.onCancellationRequested(() => {
						this.currentProcess?.kill();
						reject(new Error('Evaluation cancelled by user'));
					});

					this.currentProcess.stdout?.on('data', (data: Buffer) => {
						this.outputChannel.appendLine(data.toString().trimEnd());
					});

					this.currentProcess.stderr?.on('data', (data: Buffer) => {
						this.outputChannel.appendLine(data.toString().trimEnd());
					});

					this.currentProcess.on('close', (code) => {
						if (code === 0) {
							this.outputChannel.appendLine('');
							this.outputChannel.appendLine('---');
							this.outputChannel.appendLine('✓ Wiki evaluation completed successfully!');
							this.outputChannel.appendLine('');
							this.outputChannel.appendLine(
									`Results are in: ${params.repoDir}/`
							);
							this.printResultsHint(params);
							resolve();
						} else {
							reject(new Error(`Evaluator exited with code ${code}`));
						}
					});

					this.currentProcess.on('error', reject);
				});
			}
		);

		vscode.window.showInformationMessage(
			`Wiki evaluation completed! Results in ${params.repoDir}/`,
			'Open Output'
		).then((choice) => {
			if (choice === 'Open Output') {
				this.outputChannel.show(true);
			}
		});
	}

	// -----------------------------------------------------------------------
	// Helper: show a concise hint about where to find results
	// -----------------------------------------------------------------------

	private printResultsHint(params: EvaluationParams): void {
		const baseDir = params.repoDir;

		this.outputChannel.appendLine('📄 Evaluation report  : ' + path.join(baseDir, 'evaluation_results', 'score.md'));
		if (params.mode === 'multi-wiki') {
			this.outputChannel.appendLine('📊 CodeWiki scores    : ' + path.join(baseDir, 'evaluation_results', 'codewiki_scores.json'));
		} else {
			this.outputChannel.appendLine('📊 Detailed scores    : ' + path.join(baseDir, 'evaluation_results_combined.json'));
			this.outputChannel.appendLine('📈 Charts             : ' + path.join(baseDir, 'evaluation_charts.html'));
		}
	}
}
