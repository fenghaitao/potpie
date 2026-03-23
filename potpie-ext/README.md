# potpie-ext

A VS Code extension that embeds the Potpie UI — AI-powered code understanding and chat — directly inside the editor.

## Features

| Feature | Status |
|---|---|
| Activity Bar sidebar with Parsed Repositories tree | ✅ scaffold |
| Parse New Repo button | ✅ scaffold (logs only) |
| Wiki tab — shows repo/branch information | ✅ scaffold |
| Chat tab — agent + LLM selector, message history | ✅ scaffold (logs only) |
| Extension ↔ Webview message passing | ✅ wired up |
| Real backend integration | 🔜 TODO |

## Project Structure

```
potpie-ext/
├── src/
│   ├── extension.ts            # Activation, command registration, tree view
│   ├── repoTreeProvider.ts     # TreeDataProvider (mock repos + branches)
│   ├── state.ts                # Global state (currentRepo, currentBranch)
│   ├── sidebarChatProvider.ts  # Sidebar chat webview provider
│   ├── wikiViewerProvider.ts   # Wiki webview provider
│   └── webview/
│       ├── chatSidebar.js      # Client-side JS for chat sidebar webview
│       └── style.css           # VS Code variable–based theming
├── resources/
│   └── potpie.svg              # Activity Bar icon
├── esbuild.js                  # Bundle src/extension.ts → dist/extension.js
├── package.json
├── tsconfig.json
└── README.md
```

## Getting Started

### Prerequisites

- Node.js ≥ 18
- VS Code ≥ 1.85

### Install & build

```bash
cd potpie-ext
npm install
npm run build
```

### Run in the Extension Development Host

1. Open `potpie-ext/` as a VS Code workspace.
2. Press **F5** (or **Run → Start Debugging**).
3. A new *Extension Development Host* window opens.
4. Click the 🥧 **Potpie** icon in the Activity Bar.
5. Expand a repo node and click a branch — the main panel opens on the right.

### Watch mode (rebuild on save)

```bash
npm run watch
```

## Communication Model

```
Extension host (TypeScript)              Webview (chatSidebar.js)
─────────────────────────────────        ─────────────────────────────────
selectBranch command
  → SidebarChatProvider.notifyRepoChanged()
      → webview.postMessage({               window.addEventListener('message')
          type: 'repoChanged',                 → renderWiki(repo, branch)
          repo, branch })

                                            chatSendBtn.click()
onDidReceiveMessage ←─────────────         → vscode.postMessage({
  → console.log(chat request)                  type: 'chat',
                                               prompt, agent, llm,
                                               repo, branch })
```

## Mock Data

Two mock repositories are defined in `src/repoTreeProvider.ts`:

```
repo-alpha
  ├── main
  └── feature-x

repo-beta
  └── main
```

Replace `MOCK_REPOS` with a real API call when the backend is ready.

## License

MIT
