import * as fs from 'fs';
import * as path from 'path';

/**
 * Enum representing the supported wiki types
 */
export enum WikiType {
	CodeWiki = 'codewiki',
	DeepWiki = 'deepwiki',
	QoderWiki = 'qoder'
}

/**
 * Result of detecting wiki types in the workspace
 */
export interface WikiDetectionResult {
	hasCodeWiki: boolean;
	hasDeepWiki: boolean;
	hasQoderWiki: boolean;
	codeWikiPath?: string;
	deepWikiPath?: string;
	qoderWikiPath?: string;
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
		const qoderWikiPath = path.join(workspaceRoot, '.qoder');

		const hasCodeWiki = fs.existsSync(codeWikiPath);
		const hasDeepWiki = fs.existsSync(deepWikiPath);
		const hasQoderWiki = fs.existsSync(qoderWikiPath);

		return {
			hasCodeWiki,
			hasDeepWiki,
			hasQoderWiki,
			codeWikiPath: hasCodeWiki ? codeWikiPath : undefined,
			deepWikiPath: hasDeepWiki ? deepWikiPath : undefined,
			qoderWikiPath: hasQoderWiki ? qoderWikiPath : undefined
		};
	}

	/**
	 * Get the count of detected wikis
	 */
	public static getWikiCount(detection: WikiDetectionResult): number {
		let count = 0;
		if (detection.hasCodeWiki) count++;
		if (detection.hasDeepWiki) count++;
		if (detection.hasQoderWiki) count++;
		return count;
	}

	/**
	 * Check if any wiki exists
	 */
	public static hasAnyWiki(detection: WikiDetectionResult): boolean {
		return detection.hasCodeWiki || detection.hasDeepWiki || detection.hasQoderWiki;
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
			case WikiType.QoderWiki:
				return 'QoderWiki';
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
			case WikiType.QoderWiki:
				return 'QoderWiki pages from .qoder directory';
		}
	}
}
