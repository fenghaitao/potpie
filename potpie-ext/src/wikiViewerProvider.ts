/**
 * wikiViewerProvider.ts
 *
 * Opens wiki pages in a custom webview that renders Markdown properly,
 * including Mermaid diagrams (flowcharts, sequence diagrams, etc.).
 *
 * Approach mirrors vscode-ext/src/wikiViewerProvider.ts:
 *   - marked converts Markdown → HTML (Node.js side)
 *   - Mermaid code blocks are stored in `data-mermaid-code` attributes
 *   - A bundled mermaid.min.js renders them in the webview browser context
 *   - Theme changes are propagated to all open panels
 */
import * as fs from 'fs';
import * as path from 'path';
import * as vscode from 'vscode';
import { Marked, Renderer } from 'marked';
import { WikiPage } from './deepWikiGenerator';

// ── Mermaid counter (reset per document) ──────────────────────────────────────
let _mermaidCounter = 0;

// ── Markdown → HTML (with Mermaid stubs) ─────────────────────────────────────

function convertMarkdown(markdown: string): string {
  _mermaidCounter = 0;

  const renderer = new Renderer();

  // marked v9+: renderer methods receive a single token object.
  // Intercept fenced code blocks: mermaid → stub div, others → <pre><code>
  (renderer as any).code = (token: { text: string; lang?: string }): string => {
    const { text, lang } = token;
    if (lang === 'mermaid') {
      const id = `mermaid-diagram-${_mermaidCounter++}`;
      const escaped = text
        .replace(/\r\n/g, '\n')
        .trim()
        .replace(/&/g, '&amp;')
        .replace(/"/g, '&quot;');
      return `<div class="mermaid" id="${id}" data-mermaid-code="${escaped}"></div>`;
    }
    const escapedCode = text
      .replace(/&/g, '&amp;')
      .replace(/</g, '&lt;')
      .replace(/>/g, '&gt;');
    const langAttr = lang ? ` class="language-${lang}"` : '';
    return `<pre><code${langAttr}>${escapedCode}</code></pre>`;
  };

  // Add anchor IDs to headings for in-page navigation
  (renderer as any).heading = (token: { text: string; depth: number }): string => {
    const { text, depth } = token;
    const id = text.toLowerCase().replace(/[^\w]+/g, '-');
    return `<h${depth} id="${id}">${text}</h${depth}>\n`;
  };

  // Use a fresh Marked instance per call to avoid global state accumulation
  const instance = new Marked({ renderer, breaks: true, gfm: true });
  return instance.parse(markdown) as string;
}

// ── Nonce helper ──────────────────────────────────────────────────────────────

function nonce(): string {
  const c = 'ABCDEFGHIJKLMNOPQRSTUVWXYZabcdefghijklmnopqrstuvwxyz0123456789';
  let n = '';
  for (let i = 0; i < 32; i++) { n += c[Math.floor(Math.random() * c.length)]; }
  return n;
}

// ── Mermaid theme detection ───────────────────────────────────────────────────

function mermaidTheme(): string {
  const kind = vscode.window.activeColorTheme.kind;
  return kind === vscode.ColorThemeKind.Light || kind === vscode.ColorThemeKind.HighContrastLight
    ? 'default'
    : 'dark';
}

// ── WikiViewerProvider ────────────────────────────────────────────────────────

export class WikiViewerProvider {
  private readonly _panels = new Map<string, vscode.WebviewPanel>();
  private _themeListener: vscode.Disposable | undefined;

  constructor(private readonly _extensionUri: vscode.Uri) {
    // Propagate VS Code theme changes to all open panels
    this._themeListener = vscode.window.onDidChangeActiveColorTheme(() => {
      const theme = mermaidTheme();
      this._panels.forEach((panel) => {
        panel.webview.postMessage({ command: 'updateTheme', theme });
      });
    });
  }

  dispose(): void {
    this._themeListener?.dispose();
    this._panels.forEach((p) => p.dispose());
    this._panels.clear();
  }

  // ── Open a single file ──────────────────────────────────────────────────────

  async openWikiPage(page: WikiPage): Promise<void> {
    await this._openFile(page.filePath);
  }

  async pickAndOpen(pages: WikiPage[]): Promise<boolean> {
    const items = pages.map((p) => ({
      label: p.name,
      description: p.filePath,
      page: p,
    }));
    const pick = await vscode.window.showQuickPick(items, {
      placeHolder: 'Select a wiki page to open…',
      matchOnDescription: true,
    });
    if (!pick) { return false; }
    await this.openWikiPage(pick.page);
    return true;
  }

  // ── Internal ────────────────────────────────────────────────────────────────

  private async _openFile(filePath: string): Promise<void> {
    // Reuse existing panel for the same file
    const existing = this._panels.get(filePath);
    if (existing) { existing.reveal(); return; }

    const fileName = path.basename(filePath, '.md');
    const panel = vscode.window.createWebviewPanel(
      'potpie.wikiPage',
      `Wiki: ${fileName}`,
      vscode.ViewColumn.One,
      {
        enableScripts: true,
        retainContextWhenHidden: true,
        localResourceRoots: [this._extensionUri],
      },
    );

    this._panels.set(filePath, panel);
    panel.onDidDispose(() => this._panels.delete(filePath));

    // Handle messages from webview
    panel.webview.onDidReceiveMessage(async (msg) => {
      if (msg.command === 'openWikiLink') {
        await this._handleWikiLink(msg.href, filePath, panel);
      } else if (msg.command === 'openExternalLink') {
        vscode.env.openExternal(vscode.Uri.parse(msg.href));
      }
    });

    await this._render(panel, filePath);

    // Refresh when the file changes on disk
    const watcher = vscode.workspace.createFileSystemWatcher(filePath);
    watcher.onDidChange(() => this._render(panel, filePath));
    panel.onDidDispose(() => watcher.dispose());
  }

  private async _render(panel: vscode.WebviewPanel, filePath: string): Promise<void> {
    try {
      const raw = await fs.promises.readFile(filePath, 'utf8');
      panel.webview.html = this._buildHtml(panel.webview, raw, path.basename(filePath, '.md'));
    } catch (err) {
      vscode.window.showErrorMessage(`Potpie: failed to open wiki page — ${err}`);
    }
  }

  private async _handleWikiLink(
    href: string,
    currentFile: string,
    panel: vscode.WebviewPanel,
  ): Promise<void> {
    // Anchor-only → scroll in place
    if (href.startsWith('#')) {
      panel.webview.postMessage({ command: 'scrollToAnchor', anchor: href.slice(1) });
      return;
    }
    // Resolve relative to current file's directory
    let target = path.resolve(path.dirname(currentFile), href);
    if (!path.extname(target)) { target += '.md'; }
    if (fs.existsSync(target)) {
      await this._openFile(target);
    } else {
      vscode.window.showErrorMessage(`Potpie Wiki: link target not found — ${href}`);
    }
  }

  // ── HTML builder ────────────────────────────────────────────────────────────

  private _buildHtml(webview: vscode.Webview, markdown: string, title: string): string {
    const htmlContent = convertMarkdown(markdown);
    const nc = nonce();
    const theme = mermaidTheme();
    const csp = webview.cspSource;

    const mermaidUri = webview.asWebviewUri(
      vscode.Uri.joinPath(this._extensionUri, 'resources', 'mermaid', 'mermaid.min.js'),
    );

    return /* html */ `<!DOCTYPE html>
<html lang="en">
<head>
  <meta charset="UTF-8"/>
  <meta name="viewport" content="width=device-width, initial-scale=1.0"/>
  <meta http-equiv="Content-Security-Policy"
    content="default-src 'none';
             style-src 'unsafe-inline';
             script-src 'nonce-${nc}';
             img-src ${csp} data: https:;
             font-src ${csp};">
  <title>${title}</title>
  <style>
    body {
      font-family: var(--vscode-font-family, sans-serif);
      font-size: var(--vscode-font-size, 13px);
      color: var(--vscode-foreground);
      background-color: var(--vscode-editor-background);
      line-height: 1.6;
      padding: 24px 32px;
      max-width: 960px;
      margin: 0 auto;
    }
    h1, h2, h3, h4, h5, h6 {
      color: var(--vscode-foreground);
      margin-top: 24px;
      margin-bottom: 12px;
      font-weight: 600;
      line-height: 1.25;
    }
    h1 { font-size: 2em;   border-bottom: 1px solid var(--vscode-panel-border); padding-bottom: 0.3em; }
    h2 { font-size: 1.5em; border-bottom: 1px solid var(--vscode-panel-border); padding-bottom: 0.3em; }
    h3 { font-size: 1.25em; }
    p  { margin: 0.6em 0; }
    a  { color: var(--vscode-textLink-foreground); text-decoration: none; cursor: pointer; }
    a:hover { text-decoration: underline; }
    code {
      font-family: var(--vscode-editor-font-family, monospace);
      font-size: 0.9em;
      background-color: var(--vscode-textCodeBlock-background, rgba(255,255,255,0.1));
      padding: 2px 5px;
      border-radius: 3px;
    }
    pre {
      background-color: var(--vscode-textCodeBlock-background, rgba(255,255,255,0.06));
      padding: 14px;
      border-radius: 6px;
      overflow-x: auto;
      line-height: 1.45;
      margin: 12px 0;
    }
    pre code { background: none; padding: 0; font-size: 0.9em; }
    blockquote {
      border-left: 4px solid var(--vscode-textBlockQuote-border);
      background-color: var(--vscode-textBlockQuote-background);
      padding: 8px 16px;
      margin: 16px 0;
    }
    table {
      border-collapse: collapse;
      width: 100%;
      margin: 16px 0;
    }
    th, td { border: 1px solid var(--vscode-panel-border); padding: 8px 12px; text-align: left; }
    th { background-color: var(--vscode-editor-inactiveSelectionBackground); font-weight: 600; }
    ul, ol { padding-left: 2em; margin: 6px 0; }
    li { margin: 3px 0; }
    hr { border: none; border-top: 1px solid var(--vscode-panel-border); margin: 24px 0; }
    img { max-width: 100%; height: auto; }
    /* ── Mermaid diagram container ── */
    .mermaid {
      background-color: var(--vscode-editor-background);
      padding: 16px;
      margin: 20px 0;
      text-align: center;
      border-radius: 4px;
    }
    .mermaid svg { max-width: 100%; height: auto; }
    /* ── Mermaid error ── */
    .mermaid-error {
      background-color: var(--vscode-inputValidation-errorBackground, #5a1d1d);
      border: 1px solid var(--vscode-inputValidation-errorBorder, #f44);
      border-radius: 4px;
      padding: 14px;
      margin: 16px 0;
    }
    .mermaid-error summary { cursor: pointer; color: var(--vscode-textLink-foreground); }
    .mermaid-error pre { max-height: 200px; overflow-y: auto; margin-top: 8px; }
  </style>
  <script nonce="${nc}" src="${mermaidUri}"
    onerror="window._mermaidFailed=true"></script>
</head>
<body>
${htmlContent}
<script nonce="${nc}">
(function() {
  'use strict';
  const vscode = acquireVsCodeApi();
  let _theme = ${JSON.stringify(theme)};

  // ── Mermaid initialization ────────────────────────────────────────────────

  function initMermaid() {
    if (window._mermaidFailed || typeof mermaid === 'undefined') {
      showAllLoadErrors();
      return;
    }
    mermaid.initialize({
      startOnLoad: false,
      theme: _theme,
      // Use Mermaid's strict security mode for better sanitization of diagram content.
      // Relaxing this (e.g., to 'loose') can allow HTML/script injection and should be
      // done only with a clear, documented justification.
      securityLevel: 'strict',
      logLevel: 'error',
      maxTextSize: 50000,
      maxEdges: 500,
      deterministicIds: true,
      fontFamily: 'var(--vscode-font-family, monospace)',
    });
    renderAll();
  }

  async function renderAll() {
    const els = document.querySelectorAll('.mermaid');
    for (let i = 0; i < els.length; i++) {
      await renderOne(els[i], i);
    }
  }

  async function renderOne(el, idx) {
    const code = el.getAttribute('data-mermaid-code');
    if (!code) { return; }
    const id = el.id || ('mermaid-diagram-' + idx);
    el.id = id;
    el.removeAttribute('data-mermaid-code');
    try {
      const { svg } = await mermaid.render(id + '-svg', code);
      el.innerHTML = svg;
    } catch (err) {
      el.innerHTML = \`
        <div class="mermaid-error">
          <strong>⚠ Diagram rendering failed:</strong> \${escHtml(String(err.message || err))}
          <details>
            <summary>View diagram source</summary>
            <pre><code>\${escHtml(code)}</code></pre>
          </details>
        </div>\`;
    }
  }

  function showAllLoadErrors() {
    document.querySelectorAll('.mermaid').forEach((el, i) => {
      const code = el.getAttribute('data-mermaid-code') || '';
      el.innerHTML = \`
        <div class="mermaid-error">
          <strong>⚠ Mermaid library failed to load.</strong>
          <details>
            <summary>View diagram source</summary>
            <pre><code>\${escHtml(code)}</code></pre>
          </details>
        </div>\`;
    });
  }

  function escHtml(s) {
    return s.replace(/&/g,'&amp;').replace(/</g,'&lt;').replace(/>/g,'&gt;');
  }

  // ── Theme updates from extension ──────────────────────────────────────────

  window.addEventListener('message', (ev) => {
    const msg = ev.data;
    if (msg.command === 'updateTheme') {
      _theme = msg.theme;
      if (typeof mermaid !== 'undefined') {
        mermaid.initialize({ startOnLoad: false, theme: _theme, securityLevel: 'loose',
          logLevel: 'error', maxTextSize: 50000, maxEdges: 500, deterministicIds: true });
        renderAll();
      }
    } else if (msg.command === 'scrollToAnchor') {
      const el = document.getElementById(msg.anchor);
      if (el) { el.scrollIntoView({ behavior: 'smooth', block: 'start' }); }
    }
  });

  // ── Link interception ─────────────────────────────────────────────────────

  document.addEventListener('click', (ev) => {
    const a = ev.target.closest('a');
    if (!a) { return; }
    ev.preventDefault();
    const href = a.getAttribute('href');
    if (!href) { return; }
    if (href.startsWith('http://') || href.startsWith('https://')) {
      vscode.postMessage({ command: 'openExternalLink', href });
    } else {
      vscode.postMessage({ command: 'openWikiLink', href });
    }
  });

  // ── Boot ──────────────────────────────────────────────────────────────────
  // Use the 'load' event (fires after ALL resources including scripts) so
  // mermaid.min.js is guaranteed to be executed before we call initMermaid.
  if (document.readyState === 'complete') {
    initMermaid();
  } else {
    window.addEventListener('load', initMermaid);
  }
})();
</script>
</body>
</html>`;
  }
}

