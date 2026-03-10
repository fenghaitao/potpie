/**
 * Message protocol between extension and webview
 * 
 * Following architectural principle: Type Safety
 * All communication protocols should be strongly typed to catch errors at compile time.
 */

// ============================================================================
// Messages from Webview to Extension
// ============================================================================

/**
 * Base message interface for all webview-to-extension messages
 */
interface BaseWebviewMessage {
	command: string;
}

/**
 * Request to open a wiki link
 */
export interface OpenWikiLinkMessage extends BaseWebviewMessage {
	command: 'openWikiLink';
	href: string;
}

/**
 * Request to open an external link in browser
 */
export interface OpenExternalLinkMessage extends BaseWebviewMessage {
	command: 'openExternalLink';
	href: string;
}

/**
 * Console log message from webview
 */
export interface ConsoleLogMessage extends BaseWebviewMessage {
	command: 'consoleLog';
	message: string;
	level: 'log' | 'error' | 'warn' | 'info';
	source: string;
}

/**
 * Discriminated union of all webview-to-extension messages
 */
export type WebviewToExtensionMessage =
	| OpenWikiLinkMessage
	| OpenExternalLinkMessage
	| ConsoleLogMessage;

// ============================================================================
// Messages from Extension to Webview
// ============================================================================

/**
 * Base message interface for all extension-to-webview messages
 */
interface BaseExtensionMessage {
	command: string;
}

/**
 * Request to scroll to an anchor
 */
export interface ScrollToAnchorMessage extends BaseExtensionMessage {
	command: 'scrollToAnchor';
	anchor: string;
}

/**
 * Request to update theme
 */
export interface UpdateThemeMessage extends BaseExtensionMessage {
	command: 'updateTheme';
	theme: {
		kind: 'light' | 'dark' | 'highContrast';
		mermaidTheme: string;
		cssVariables: Record<string, string>;
	};
}

/**
 * Discriminated union of all extension-to-webview messages
 */
export type ExtensionToWebviewMessage =
	| ScrollToAnchorMessage
	| UpdateThemeMessage;

// ============================================================================
// Type Guards
// ============================================================================

/**
 * Type guard for OpenWikiLinkMessage
 */
export function isOpenWikiLinkMessage(msg: WebviewToExtensionMessage): msg is OpenWikiLinkMessage {
	return msg.command === 'openWikiLink';
}

/**
 * Type guard for OpenExternalLinkMessage
 */
export function isOpenExternalLinkMessage(msg: WebviewToExtensionMessage): msg is OpenExternalLinkMessage {
	return msg.command === 'openExternalLink';
}

/**
 * Type guard for ConsoleLogMessage
 */
export function isConsoleLogMessage(msg: WebviewToExtensionMessage): msg is ConsoleLogMessage {
	return msg.command === 'consoleLog';
}

/**
 * Type guard for ScrollToAnchorMessage
 */
export function isScrollToAnchorMessage(msg: ExtensionToWebviewMessage): msg is ScrollToAnchorMessage {
	return msg.command === 'scrollToAnchor';
}

/**
 * Type guard for UpdateThemeMessage
 */
export function isUpdateThemeMessage(msg: ExtensionToWebviewMessage): msg is UpdateThemeMessage {
	return msg.command === 'updateTheme';
}
