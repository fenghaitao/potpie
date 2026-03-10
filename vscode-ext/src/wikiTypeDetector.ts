import * as fs from 'fs';
import * as path from 'path';

/**
 * Enum representing the supported wiki types
 */
export enum WikiType {
	CodeWiki = 'codewiki',
	DeepWiki = 'deepwiki'
}

/**
 * Result of detecting wiki types in the workspace
 */
export interface WikiDetectionResult {
	hasCodeWiki: boolean;
	hasDeepWiki: boolean;
	codeWikiPath?: string;
	deepWikiPath?: string;
}

/**
 * Utility class for detecting and managing wiki types
 */
export class WikiTypeDetector {
	/**
	 * Detect which wiki types exist in the workspace
	 * @param workspaceRoot The root path of the workspace
	 * @returns Detection result with paths to found wikis
	 */
	public static detect(workspaceRoot: string): WikiDetectionResult {
		const codeWikiPath = path.join(workspaceRoot, '.codewiki');
		const deepWikiPath = path.join(workspaceRoot, '.deepwiki');

		const hasCodeWiki = fs.existsSync(codeWikiPath);
		const hasDeepWiki = fs.existsSync(deepWikiPath);

		return {
			hasCodeWiki,
			hasDeepWiki,
			codeWikiPath: hasCodeWiki ? codeWikiPath : undefined,
			deepWikiPath: hasDeepWiki ? deepWikiPath : undefined
		};
	}

	/**
	 * Get the count of detected wikis
	 */
	public static getWikiCount(detection: WikiDetectionResult): number {
		let count = 0;
		if (detection.hasCodeWiki) count++;
		if (detection.hasDeepWiki) count++;
		return count;
	}

	/**
	 * Check if any wiki exists
	 */
	public static hasAnyWiki(detection: WikiDetectionResult): boolean {
		return detection.hasCodeWiki || detection.hasDeepWiki;
	}

	/**
	 * Get the wiki path for a specific type
	 */
	public static getWikiPath(workspaceRoot: string, type: WikiType): string {
		return path.join(workspaceRoot, `.${type}`);
	}

	/**
	 * Get display name for wiki type
	 */
	public static getDisplayName(type: WikiType): string {
		switch (type) {
			case WikiType.CodeWiki:
				return 'CodeWiki';
			case WikiType.DeepWiki:
				return 'DeepWiki';
		}
	}

	/**
	 * Get description for wiki type
	 */
	public static getDescription(type: WikiType): string {
		switch (type) {
			case WikiType.CodeWiki:
				return 'Standard repository documentation with module structure';
			case WikiType.DeepWiki:
				return 'Deep analysis with enhanced AI-powered insights';
		}
	}
}
