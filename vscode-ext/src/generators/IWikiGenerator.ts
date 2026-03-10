import * as vscode from 'vscode';
import { WikiType } from '../wikiTypeDetector';

/**
 * Progress callback for generation updates
 */
export interface GenerationProgress {
	/**
	 * Report generation progress
	 */
	report(message: string): void;
}

/**
 * Interface for wiki generators
 */
export interface IWikiGenerator {
	/**
	 * Get the wiki type this generator handles
	 */
	getWikiType(): WikiType;

	/**
	 * Generate wiki documentation for the workspace
	 * @param workspaceRoot The root path of the workspace
	 * @param progress Progress reporter for UI updates
	 * @param cancellationToken Token to signal cancellation
	 * @returns Promise that resolves when generation is complete
	 */
	generate(
		workspaceRoot: string,
		progress: GenerationProgress,
		cancellationToken: vscode.CancellationToken
	): Promise<void>;

	/**
	 * Check if the generator's prerequisites are met
	 * @param workspaceRoot The root path of the workspace
	 * @returns Promise that resolves to true if ready, false otherwise
	 */
	checkPrerequisites(workspaceRoot: string): Promise<boolean>;
}
