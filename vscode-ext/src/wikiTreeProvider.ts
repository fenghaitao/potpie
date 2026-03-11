import * as fs from 'fs';
import * as path from 'path';
import * as vscode from 'vscode';
import { WikiType, WikiTypeDetector, WikiDetectionResult } from './wikiTypeDetector';
import { DeepWikiXmlParser, DeepWikiStructure, DeepWikiSection, DeepWikiPage } from './deepwiki/xmlParser';

interface ModuleTreeNode {
	path?: string;
	components?: string[];
	children?: { [key: string]: ModuleTreeNode };
}

interface ModuleTree {
	[key: string]: ModuleTreeNode;
}

export class WikiTreeItem extends vscode.TreeItem {
	constructor(
		label: string,
		collapsibleState: vscode.TreeItemCollapsibleState,
		public readonly resourcePath: string,
		public readonly isDirectory: boolean,
		public readonly isOverview: boolean = false,
		public readonly moduleKey?: string,
		public readonly wikiType?: WikiType,
		public readonly deepwikiSection?: DeepWikiSection,
		public readonly deepwikiPage?: DeepWikiPage,
		public readonly pagePath?: string  // optional page to open when clicking a folder
	) {
		// Remove .md suffix from display name, format module names nicely
		let displayLabel = label.endsWith('.md') ? label.slice(0, -3) : label;
		
		// For overview, show a home icon
		if (isOverview) {
			displayLabel = '📚 ' + displayLabel;
		} 
		// For DeepWiki pages and sections, use the title as-is (already properly formatted)
		else if (deepwikiPage || deepwikiSection) {
			// Keep the label as-is for DeepWiki items
			displayLabel = label;
		}
		// For CodeWiki modules, convert snake_case to Title Case
		else {
			displayLabel = displayLabel.split('_').map(word => 
				word.charAt(0).toUpperCase() + word.slice(1)
			).join(' ');
		}
		
		super(displayLabel, collapsibleState);
		this.tooltip = this.resourcePath;
		this.contextValue = isOverview ? 'overview' : (isDirectory ? 'folder' : 'file');

		// Add open command for non-directory items, overview, or folders that have a matching page
		const openPath = pagePath ?? ((!isDirectory || isOverview) ? this.resourcePath : undefined);
		if (openPath) {
			this.command = {
				command: 'codewiki.openFile',
				title: 'Open Wiki File',
				arguments: [openPath, wikiType]
			};
			this.iconPath = isOverview
				? new vscode.ThemeIcon('home')
				: new vscode.ThemeIcon('file');
		} else {
			this.iconPath = new vscode.ThemeIcon('folder');
		}
	}
}

const SELECTED_WIKI_TYPE_KEY = 'codewiki.selectedWikiType';

export class CodeWikiTreeProvider implements vscode.TreeDataProvider<WikiTreeItem> {
	private _onDidChangeTreeData: vscode.EventEmitter<WikiTreeItem | undefined | null | void> = new vscode.EventEmitter<WikiTreeItem | undefined | null | void>();
	readonly onDidChangeTreeData: vscode.Event<WikiTreeItem | undefined | null | void> = this._onDidChangeTreeData.event;

	private workspaceRoot: string | undefined;
	private wikiDetection: WikiDetectionResult | undefined;
	private selectedWikiType: WikiType | undefined;
	private wikiPath: string | undefined;
	private hasWiki: boolean = false;
	private moduleTree: ModuleTree | undefined;
	private deepwikiStructure: DeepWikiStructure | undefined;
	private workspaceState: vscode.Memento | undefined;

	constructor(workspaceState?: vscode.Memento) {
		this.workspaceState = workspaceState;
		this.updateWorkspaceRoot();
	}

	public getHasWiki(): boolean {
		return this.hasWiki;
	}

	public getWikiDetection(): WikiDetectionResult | undefined {
		return this.wikiDetection;
	}

	public setSelectedWikiType(type: WikiType | undefined) {
		this.selectedWikiType = type;
		if (this.workspaceState) {
			this.workspaceState.update(SELECTED_WIKI_TYPE_KEY, type);
		}
		this.updateWikiPath();
		this.refresh();
	}

	public getSelectedWikiType(): WikiType | undefined {
		return this.selectedWikiType;
	}

	public getViewTitle(): string {
		// If DeepWiki is selected and has a title, use it
		if (this.selectedWikiType === WikiType.DeepWiki && this.deepwikiStructure?.title) {
			return this.deepwikiStructure.title;
		}
		
		// Default titles
		if (this.selectedWikiType === WikiType.CodeWiki) {
			return 'Repository Wiki';
		} else if (this.selectedWikiType === WikiType.DeepWiki) {
			return 'DeepWiki Documentation';
		} else if (this.selectedWikiType === WikiType.QoderWiki) {
			return 'QoderWiki';
		}
		
		return 'Repository Wiki';
	}

	private loadModuleTree(): ModuleTree | undefined {
		if (!this.wikiPath) {
			return undefined;
		}

		const moduleTreePath = path.join(this.wikiPath, 'module_tree.json');
		if (!fs.existsSync(moduleTreePath)) {
			return undefined;
		}

		try {
			const content = fs.readFileSync(moduleTreePath, 'utf-8');
			const tree = JSON.parse(content) as ModuleTree;
			return tree;
		} catch (error) {
			return undefined;
		}
	}

	private loadDeepWikiStructure(): DeepWikiStructure | undefined {
		if (!this.wikiPath) {
			return undefined;
		}

	const xmlPath = path.join(this.wikiPath, 'wiki_structure.xml');
	if (!fs.existsSync(xmlPath)) {
		return undefined;
	}

	try {
		const structure = DeepWikiXmlParser.parse(xmlPath);
		return structure;
	} catch (error) {
		console.error('Error loading wiki_structure.xml:', error);
		return undefined;
	}
}	private updateWorkspaceRoot() {
		const workspaceFolders = vscode.workspace.workspaceFolders;
		if (workspaceFolders && workspaceFolders.length > 0) {
			this.workspaceRoot = workspaceFolders[0].uri.fsPath;
			
			// Detect available wiki types
			this.wikiDetection = WikiTypeDetector.detect(this.workspaceRoot);
			
			// Determine selected wiki type
			if (!this.selectedWikiType) {
				// Restore persisted selection if available and valid
				const persisted = this.workspaceState?.get<WikiType>(SELECTED_WIKI_TYPE_KEY);
				if (persisted === WikiType.CodeWiki && this.wikiDetection.hasCodeWiki) {
					this.selectedWikiType = WikiType.CodeWiki;
				} else if (persisted === WikiType.DeepWiki && this.wikiDetection.hasDeepWiki) {
					this.selectedWikiType = WikiType.DeepWiki;
				} else if (persisted === WikiType.QoderWiki && this.wikiDetection.hasQoderWiki) {
					this.selectedWikiType = WikiType.QoderWiki;
				} else if (WikiTypeDetector.getWikiCount(this.wikiDetection) === 1) {
					// Auto-select if only one exists
					if (this.wikiDetection.hasCodeWiki) {
						this.selectedWikiType = WikiType.CodeWiki;
					} else if (this.wikiDetection.hasDeepWiki) {
						this.selectedWikiType = WikiType.DeepWiki;
					} else if (this.wikiDetection.hasQoderWiki) {
						this.selectedWikiType = WikiType.QoderWiki;
					}
				}
				// If multiple or none exist, selectedWikiType remains undefined
			}
			
			this.updateWikiPath();
			
			
			// Update context for views
			vscode.commands.executeCommand('setContext', 'codewiki.hasWiki', this.hasWiki);
			vscode.commands.executeCommand('setContext', 'codewiki.hasCodeWiki', this.wikiDetection.hasCodeWiki);
			vscode.commands.executeCommand('setContext', 'codewiki.hasDeepWiki', this.wikiDetection.hasDeepWiki);
			vscode.commands.executeCommand('setContext', 'codewiki.hasQoderWiki', this.wikiDetection.hasQoderWiki);
			vscode.commands.executeCommand('setContext', 'codewiki.hasBothWikis', 
				WikiTypeDetector.getWikiCount(this.wikiDetection) >= 2);
		} else {
			this.workspaceRoot = undefined;
			this.wikiPath = undefined;
			this.hasWiki = false;
			this.wikiDetection = undefined;
			this.moduleTree = undefined;
			vscode.commands.executeCommand('setContext', 'codewiki.hasWiki', false);
			vscode.commands.executeCommand('setContext', 'codewiki.hasCodeWiki', false);
			vscode.commands.executeCommand('setContext', 'codewiki.hasDeepWiki', false);
			vscode.commands.executeCommand('setContext', 'codewiki.hasQoderWiki', false);
			vscode.commands.executeCommand('setContext', 'codewiki.hasBothWikis', false);
		}
	}

	private updateWikiPath() {
		if (!this.workspaceRoot || !this.selectedWikiType) {
			this.wikiPath = undefined;
			this.hasWiki = false;
			this.moduleTree = undefined;
			this.deepwikiStructure = undefined;
			return;
		}

		this.wikiPath = WikiTypeDetector.getWikiPath(this.workspaceRoot, this.selectedWikiType);
		this.hasWiki = fs.existsSync(this.wikiPath);
		
		// Load appropriate structure based on wiki type
		if (this.hasWiki) {
			if (this.selectedWikiType === WikiType.CodeWiki) {
				this.moduleTree = this.loadModuleTree();
				this.deepwikiStructure = undefined;
			} else if (this.selectedWikiType === WikiType.DeepWiki) {
				this.deepwikiStructure = this.loadDeepWikiStructure();
				this.moduleTree = undefined;
			} else if (this.selectedWikiType === WikiType.QoderWiki) {
				// QoderWiki uses the filesystem scanner directly - no structure files
				this.moduleTree = undefined;
				this.deepwikiStructure = undefined;
			}
		} else {
			this.moduleTree = undefined;
			this.deepwikiStructure = undefined;
		}
	}

	refresh(): void {
		this.updateWorkspaceRoot();
		this._onDidChangeTreeData.fire();
	}

	getTreeItem(element: WikiTreeItem): vscode.TreeItem {
		return element;
	}

	async getChildren(element?: WikiTreeItem): Promise<WikiTreeItem[]> {

		if (!this.wikiPath) {
			return [];
		}

		if (!fs.existsSync(this.wikiPath)) {
			return [];
		}

		// Root level: show overview.md at top, then modules from module_tree or DeepWiki sections
		if (!element) {
			const items: WikiTreeItem[] = [];
			
			// CodeWiki: Add overview.md as the first item (home page)
			// QoderWiki: skip wrapper dirs (e.g. repowiki/en/content/) and scan real content root
			if (this.selectedWikiType === WikiType.QoderWiki) {
				const contentRoot = this.resolveQoderContentRoot(this.wikiPath);
				return this.scanFileSystem(contentRoot);
			}
			
			if (this.selectedWikiType === WikiType.CodeWiki) {
				const overviewPath = path.join(this.wikiPath, 'overview.md');
				if (fs.existsSync(overviewPath)) {
					items.push(new WikiTreeItem(
						'Overview',
						vscode.TreeItemCollapsibleState.None,
						overviewPath,
						false,
						true, // isOverview
						undefined,
						this.selectedWikiType
					));
				}
			}
			
			// If we have module_tree.json (CodeWiki), use it to build the hierarchy
			if (this.moduleTree) {
				const moduleItems = this.buildModuleTreeItems(this.moduleTree);
				items.push(...moduleItems);
			}
			// If we have DeepWiki structure, build from sections
			else if (this.deepwikiStructure) {
				const deepwikiItems = this.buildDeepWikiTreeItems(this.deepwikiStructure);
				items.push(...deepwikiItems);
			}
			// Fallback to file system scanning if no structure file
			else {
				const fsItems = await this.scanFileSystem(this.wikiPath);
				items.push(...fsItems);
			}
			
			return items;
		}

		// For DeepWiki section nodes, show their pages and subsections
		if (element.deepwikiSection) {
			return this.getDeepWikiSectionChildren(element.deepwikiSection);
		}

		// For module nodes, show their children
		if (element.moduleKey && this.moduleTree) {
			const childItems = this.getModuleChildren(element.moduleKey);
			return childItems;
		}

		// For QoderWiki (and filesystem-scanned) directory nodes, scan the subdirectory
		if (element.isDirectory && element.resourcePath) {
			return this.scanFileSystem(element.resourcePath);
		}

		// Fallback: shouldn't reach here if using module tree or deepwiki structure
		return [];
	}

	private buildModuleTreeItems(tree: ModuleTree, parentKey?: string): WikiTreeItem[] {
		const items: WikiTreeItem[] = [];
		
		for (const [key, node] of Object.entries(tree)) {
			const fullKey = parentKey ? `${parentKey}.${key}` : key;
			const mdPath = path.join(this.wikiPath!, `${key}.md`);
			
			// Check if this module has children
			const hasChildren = !!(node.children && Object.keys(node.children).length > 0);
			const collapsibleState = hasChildren 
				? vscode.TreeItemCollapsibleState.Collapsed 
				: vscode.TreeItemCollapsibleState.None;
			
			items.push(new WikiTreeItem(
				key,
				collapsibleState,
				mdPath,
				hasChildren,
				false,
				fullKey,
				this.selectedWikiType
			));
		}
		
		// Sort alphabetically
		items.sort((a, b) => {
			const labelA = typeof a.label === 'string' ? a.label : (a.label?.label ?? '');
			const labelB = typeof b.label === 'string' ? b.label : (b.label?.label ?? '');
			return labelA.localeCompare(labelB);
		});
		
		return items;
	}

	private getModuleChildren(moduleKey: string): WikiTreeItem[] {
		if (!this.moduleTree) {
			return [];
		}

		// Navigate to the module in the tree
		const parts = moduleKey.split('.');
		let currentNode: ModuleTreeNode | undefined;
		let currentTree: ModuleTree | { [key: string]: ModuleTreeNode } = this.moduleTree;

		for (const part of parts) {
			currentNode = currentTree[part];
			if (!currentNode) {
				return [];
			}
			currentTree = currentNode.children || {};
		}

		// Build items for children
		if (currentNode?.children) {
			return this.buildModuleTreeItems(currentNode.children, moduleKey);
		}

		return [];
	}

	private resolveQoderContentRoot(dir: string): string {
		// Walk down skipping intermediate wrapper directories that contain only
		// a single subdirectory and no markdown files, so we land on the real
		// content folder (e.g. .qoder/repowiki/en/content -> show content directly).
		let current = dir;
		for (let depth = 0; depth < 10; depth++) {
			let entries: fs.Dirent[];
			try {
				entries = fs.readdirSync(current, { withFileTypes: true });
			} catch {
				break;
			}
			const dirs = entries.filter(e => e.isDirectory());
			const mdFiles = entries.filter(e => !e.isDirectory() && e.name.endsWith('.md'));
			// Stop when there are markdown files, multiple subdirs, or no subdirs at all
			if (mdFiles.length > 0 || dirs.length !== 1) {
				break;
			}
			current = path.join(current, dirs[0].name);
		}
		return current;
	}

	private async scanFileSystem(targetPath: string): Promise<WikiTreeItem[]> {
		try {
			const items = await fs.promises.readdir(targetPath, { withFileTypes: true });
			const treeItems: WikiTreeItem[] = [];

			for (const item of items) {
				const fullPath = path.join(targetPath, item.name);
				const isDirectory = item.isDirectory();

				// Skip overview.md (already shown at top) and non-markdown files
				if (item.name === 'overview.md' || 
					item.name === 'module_tree.json' || 
					item.name === 'metadata.json' || 
					item.name === 'first_module_tree.json' ||
					item.name === 'wiki_structure.xml') {
					continue;
				}

				// Only show markdown files and directories
				if (!isDirectory && !item.name.endsWith('.md')) {
					continue;
				}

				// Skip a .md file whose name matches the parent directory name
				// (it is the folder's overview page; rendered when clicking the folder)
				const parentDirName = path.basename(targetPath);
				if (!isDirectory && item.name === parentDirName + '.md') {
					continue;
				}

				// Skip temp directory
				if (isDirectory && item.name === 'temp') {
					continue;
				}

				const collapsibleState = isDirectory
					? vscode.TreeItemCollapsibleState.Collapsed
					: vscode.TreeItemCollapsibleState.None;

				// For directories, check if there's a same-named .md file inside (e.g. "API Reference/API Reference.md")
				let pagePath: string | undefined;
				if (isDirectory) {
					const candidate = path.join(fullPath, item.name + '.md');
					if (fs.existsSync(candidate)) {
						pagePath = candidate;
					}
				}

				treeItems.push(new WikiTreeItem(
					item.name,
					collapsibleState,
					fullPath,
					isDirectory,
					false,
					undefined,
					this.selectedWikiType,
					undefined,
					undefined,
					pagePath
				));
			}

			// Sort: directories first, then files, all alphabetically
			treeItems.sort((a, b) => {
				const labelA = typeof a.label === 'string' ? a.label : (a.label?.label ?? '');
				const labelB = typeof b.label === 'string' ? b.label : (b.label?.label ?? '');
				
				// Directories before files
				if (a.isDirectory && !b.isDirectory) {
					return -1;
				}
				if (!a.isDirectory && b.isDirectory) {
					return 1;
				}
				
				// Then alphabetically
				return labelA.localeCompare(labelB);
			});

			return treeItems;
		} catch (error) {
			return [];
		}
	}


private buildDeepWikiTreeItems(structure: DeepWikiStructure): WikiTreeItem[] {
	const items: WikiTreeItem[] = [];

	for (const section of structure.sections) {
		const hasContent = section.pages.length > 0 || section.subsections.length > 0;
		const collapsibleState = hasContent 
			? vscode.TreeItemCollapsibleState.Collapsed 
			: vscode.TreeItemCollapsibleState.None;

		// Sections don't have their own files, they're just containers
		items.push(new WikiTreeItem(
			section.title,
			collapsibleState,
			'', // No resource path for sections
			true, // Treat as directory
			false,
			undefined,
			this.selectedWikiType,
			section, // Store section reference
			undefined
		));
	}

	return items;
}
private getDeepWikiSectionChildren(section: DeepWikiSection): WikiTreeItem[] {
	const items: WikiTreeItem[] = [];

	// Add pages first
	for (const page of section.pages) {
		const pagePath = path.join(this.wikiPath!, page.fileName);
		
		items.push(new WikiTreeItem(
			page.title,
			vscode.TreeItemCollapsibleState.None,
			pagePath,
			false,
			false,
			undefined,
			this.selectedWikiType,
			undefined,
			page // Store page reference
		));
	}

	// Then add subsections
	for (const subsection of section.subsections) {
		const hasContent = subsection.pages.length > 0 || subsection.subsections.length > 0;
		const collapsibleState = hasContent 
			? vscode.TreeItemCollapsibleState.Collapsed 
			: vscode.TreeItemCollapsibleState.None;

		items.push(new WikiTreeItem(
			subsection.title,
			collapsibleState,
			'', // No resource path for sections
			true,
			false,
			undefined,
			this.selectedWikiType,
			subsection,
			undefined
		));
	}

	return items;
}
}