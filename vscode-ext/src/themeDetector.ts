import * as vscode from 'vscode';

/**
 * Theme information for Mermaid diagrams
 */
export interface IThemeInfo {
	/** VSCode theme kind */
	kind: 'light' | 'dark' | 'highContrast';
	/** Mermaid theme name */
	mermaidTheme: string;
	/** CSS variables for custom styling */
	cssVariables: Record<string, string>;
}

/**
 * Theme detector that maps VSCode themes to Mermaid themes
 */
export class ThemeDetector {
	/**
	 * Get current theme information
	 */
	public static getCurrentTheme(): IThemeInfo {
		const colorTheme = vscode.window.activeColorTheme;
		const kind = this.mapThemeKind(colorTheme.kind);
		
		// Check user settings for theme override
		const config = vscode.workspace.getConfiguration('codewiki.mermaid');
		const themePreference = config.get<string>('theme', 'auto');
		
		let mermaidTheme: string;
		if (themePreference === 'auto') {
			mermaidTheme = this.mapToMermaidTheme(colorTheme.kind);
		} else {
			mermaidTheme = themePreference;
		}
		
		const cssVariables = this.extractCssVariables(colorTheme.kind);

		return {
			kind,
			mermaidTheme,
			cssVariables
		};
	}

	/**
	 * Map VSCode theme kind to our theme kind
	 */
	private static mapThemeKind(kind: vscode.ColorThemeKind): 'light' | 'dark' | 'highContrast' {
		switch (kind) {
			case vscode.ColorThemeKind.Light:
				return 'light';
			case vscode.ColorThemeKind.Dark:
				return 'dark';
			case vscode.ColorThemeKind.HighContrast:
			case vscode.ColorThemeKind.HighContrastLight:
				return 'highContrast';
			default:
				return 'dark';
		}
	}

	/**
	 * Map VSCode theme kind to Mermaid theme name
	 */
	private static mapToMermaidTheme(kind: vscode.ColorThemeKind): string {
		switch (kind) {
			case vscode.ColorThemeKind.Light:
			case vscode.ColorThemeKind.HighContrastLight:
				return 'default'; // Mermaid's default theme is light
			case vscode.ColorThemeKind.Dark:
				return 'dark';
			case vscode.ColorThemeKind.HighContrast:
				return 'dark'; // Use dark theme for high contrast
			default:
				return 'dark';
		}
	}

	/**
	 * Extract CSS variables for Mermaid styling
	 */
	private static extractCssVariables(kind: vscode.ColorThemeKind): Record<string, string> {
		const isDark = kind === vscode.ColorThemeKind.Dark || kind === vscode.ColorThemeKind.HighContrast;
		
		// Define CSS variables that will be used in the webview
		return {
			'--mermaid-background': isDark ? '#1e1e1e' : '#ffffff',
			'--mermaid-primary-color': isDark ? '#569cd6' : '#0066cc',
			'--mermaid-secondary-color': isDark ? '#4ec9b0' : '#008080',
			'--mermaid-text-color': isDark ? '#d4d4d4' : '#000000',
			'--mermaid-border-color': isDark ? '#3e3e3e' : '#cccccc',
			'--mermaid-note-background': isDark ? '#2d2d2d' : '#f0f0f0'
		};
	}

	/**
	 * Create a theme change listener
	 */
	public static onThemeChange(callback: (theme: IThemeInfo) => void): vscode.Disposable {
		return vscode.window.onDidChangeActiveColorTheme(() => {
			const theme = this.getCurrentTheme();
			callback(theme);
		});
	}
}
