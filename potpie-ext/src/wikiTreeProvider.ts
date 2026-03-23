/**
 * wikiTreeProvider.ts
 *
 * Tree data provider for the "Wiki" sidebar view (potpie.wikiView).
 *
 * Path layout (potpie-ext, different from vscode-ext):
 *   contentDir  =  <workspacePath>/wikis/<repo>_<branch>/en/content/
 *   wiki_structure.xml  =  contentDir/../../wiki_structure.xml
 *   page file   =  contentDir/<SectionTitle_Underscored>/<PageTitle_Underscored>.md
 *
 * In vscode-ext pages are flat inside the wiki root; here they live in
 * per-section subdirectories.  HTML entities in section titles (&amp; → &)
 * must be decoded before converting to directory names.
 */
import * as fs from 'fs';
import * as path from 'path';
import * as vscode from 'vscode';
import { DeepWikiXmlParser, DeepWikiSection } from './deepwiki/xmlParser';

// ── Re-export so extension.ts can import from one place ──────────────────────

export type WikiState = 'no-repo' | 'missing' | 'generating' | 'ready';

// ── Tree items ────────────────────────────────────────────────────────────────

/** A section node (collapsible folder) */
export class WikiSectionItem extends vscode.TreeItem {
  constructor(
    public readonly section: DeepWikiSection,
    /** Absolute path to the directory where this section's pages live. */
    public readonly sectionDir: string,
    collapsibleState: vscode.TreeItemCollapsibleState,
  ) {
    super(_htmlDecode(section.title), collapsibleState);
    this.iconPath    = new vscode.ThemeIcon('folder');
    this.contextValue = 'wiki-section';
  }
}

/** A page node (leaf file) */
class WikiPageItem extends vscode.TreeItem {
  constructor(title: string, filePath: string) {
    super(title, vscode.TreeItemCollapsibleState.None);
    this.iconPath     = new vscode.ThemeIcon('file');
    this.contextValue = 'wiki-page';
    this.tooltip      = filePath;
    this.command      = {
      command: 'potpie.openWikiPage',
      title: 'Open Wiki Page',
      arguments: [filePath],
    };
  }
}

/** A single-item placeholder for non-ready states. */
class WikiStatusItem extends vscode.TreeItem {
  constructor(label: string, icon: string) {
    super(label, vscode.TreeItemCollapsibleState.None);
    this.iconPath     = new vscode.ThemeIcon(icon);
    this.contextValue = 'wiki-status';
  }
}

// ── Provider ─────────────────────────────────────────────────────────────────

export class WikiTreeProvider
  implements vscode.TreeDataProvider<vscode.TreeItem>
{
  private readonly _onDidChangeTreeData =
    new vscode.EventEmitter<vscode.TreeItem | undefined | null | void>();
  readonly onDidChangeTreeData = this._onDidChangeTreeData.event;

  private _state: WikiState = 'no-repo';
  private _contentDir: string | undefined;
  private _structure: ReturnType<typeof DeepWikiXmlParser.parse> | undefined;

  // ── Public API ────────────────────────────────────────────────────────────

  /**
   * Update the provider state.
   *
   * @param state       New state.
   * @param contentDir  Required when state === 'ready'.  Ignored otherwise but
   *                    remembered so a subsequent 'ready' call can reuse it.
   */
  setState(state: WikiState, contentDir?: string): void {
    this._state = state;
    if (contentDir !== undefined) { this._contentDir = contentDir; }

    if (state === 'ready' && this._contentDir) {
      this._loadStructure();
    } else if (state !== 'ready') {
      this._structure = undefined;
    }

    this._onDidChangeTreeData.fire();
  }

  // ── TreeDataProvider ──────────────────────────────────────────────────────

  getTreeItem(element: vscode.TreeItem): vscode.TreeItem {
    return element;
  }

  getChildren(element?: vscode.TreeItem): vscode.ProviderResult<vscode.TreeItem[]> {
    // ── Root level ────────────────────────────────────────────────────────
    if (!element) {
      switch (this._state) {
        case 'no-repo':
          return [new WikiStatusItem(
            'Select a repository to view its wiki.',
            'repo',
          )];

        case 'missing':
          // Return [] so viewsWelcome shows the "Generate DeepWiki" button.
          return [];

        case 'generating':
          return [new WikiStatusItem(
            'Generating wiki\u2026 This may take several minutes.',
            'loading~spin',
          )];

        case 'ready':
          if (this._structure && this._contentDir) {
            return this._buildSectionItems(this._structure.sections, this._contentDir);
          }
          // No XML structure — fall back to filesystem scan
          return this._contentDir ? this._scanFileSystem(this._contentDir) : [];
      }
    }

    // ── Section children ──────────────────────────────────────────────────
    if (element instanceof WikiSectionItem) {
      return this._getSectionChildren(element.section, element.sectionDir);
    }

    return [];
  }

  // ── Private helpers ───────────────────────────────────────────────────────

  /**
   * Map a section title to the directory name used by the DeepWiki generator.
   *
   * The Python generator's `_to_filename(...)` collapses all characters that
   * are not in `[A-Za-z0-9_-]` to underscores. We mirror that here so that
   * section/subsection paths line up with the on-disk layout while the tree
   * still displays the human-readable (decoded) title.
   */
  private _sectionDirFromTitle(title: string): string {
    const decoded = _htmlDecode(title);
    // Replace any run of characters outside [A-Za-z0-9_-] with a single "_".
    return decoded.replace(/[^A-Za-z0-9_-]+/g, '_');
  }

  private _loadStructure(): void {
    if (!this._contentDir) { return; }
    // wiki_structure.xml is two levels above contentDir:
    //   <base>/en/content/  →  <base>/wiki_structure.xml
    const xmlPath = path.resolve(this._contentDir, '..', '..', 'wiki_structure.xml');
    if (!fs.existsSync(xmlPath)) {
      this._structure = undefined;
      return;
    }
    try {
      this._structure = DeepWikiXmlParser.parse(xmlPath);
    } catch {
      this._structure = undefined;
    }
  }

  private _buildSectionItems(
    sections: DeepWikiSection[],
    contentDir: string,
  ): WikiSectionItem[] {
    return sections.map((section) => {
      const hasContent = section.pages.length > 0 || section.subsections.length > 0;
      // Section directory name must match DeepWiki's `_to_filename(...)`
      const dirName   = this._sectionDirFromTitle(section.title);
      const sectionDir = path.join(contentDir, dirName);
      return new WikiSectionItem(
        section,
        sectionDir,
        hasContent
          ? vscode.TreeItemCollapsibleState.Collapsed
          : vscode.TreeItemCollapsibleState.None,
      );
    });
  }

  private _getSectionChildren(
    section: DeepWikiSection,
    sectionDir: string,
  ): vscode.TreeItem[] {
    const items: vscode.TreeItem[] = [];

    // Pages in this section
    for (const page of section.pages) {
      const filePath = path.join(sectionDir, page.fileName);
      if (fs.existsSync(filePath)) {
        items.push(new WikiPageItem(page.title, filePath));
      }
    }

    // Subsections — try a same-name subdirectory; fall back to sectionDir
    for (const sub of section.subsections) {
      const subDirName = this._sectionDirFromTitle(sub.title);
      const candidateDir = path.join(sectionDir, subDirName);
      const subDir = fs.existsSync(candidateDir) ? candidateDir : sectionDir;
      const hasContent = sub.pages.length > 0 || sub.subsections.length > 0;
      items.push(new WikiSectionItem(
        sub,
        subDir,
        hasContent
          ? vscode.TreeItemCollapsibleState.Collapsed
          : vscode.TreeItemCollapsibleState.None,
      ));
    }

    return items;
  }

  /** Filesystem fallback when wiki_structure.xml is absent. */
  private _scanFileSystem(dir: string): vscode.TreeItem[] {
    try {
      const entries = fs.readdirSync(dir, { withFileTypes: true });
      const items: vscode.TreeItem[] = [];

      for (const entry of entries) {
        const fullPath = path.join(dir, entry.name);
        if (entry.isDirectory()) {
          // Represent directory as a section without XML metadata
          const fakeSection: DeepWikiSection = {
            id: entry.name,
            title: entry.name.replace(/_/g, ' '),
            pages: [],
            subsections: [],
          };
          items.push(new WikiSectionItem(
            fakeSection,
            fullPath,
            vscode.TreeItemCollapsibleState.Collapsed,
          ));
        } else if (entry.name.endsWith('.md')) {
          const title = entry.name.replace(/\.md$/, '').replace(/_/g, ' ');
          items.push(new WikiPageItem(title, fullPath));
        }
      }

      items.sort((a, b) => {
        const la = typeof a.label === 'string' ? a.label : (a.label?.label ?? '');
        const lb = typeof b.label === 'string' ? b.label : (b.label?.label ?? '');
        const isADir = a instanceof WikiSectionItem;
        const isBDir = b instanceof WikiSectionItem;
        if (isADir !== isBDir) { return isADir ? -1 : 1; }
        return la.localeCompare(lb);
      });

      return items;
    } catch {
      return [];
    }
  }
}

// ── Utility ───────────────────────────────────────────────────────────────────

/** Decode the XML entities that the wiki generator may emit in titles. */
function _htmlDecode(str: string): string {
  return str
    .replace(/&amp;/g, '&')
    .replace(/&lt;/g, '<')
    .replace(/&gt;/g, '>')
    .replace(/&quot;/g, '"')
    .replace(/&apos;/g, "'");
}
