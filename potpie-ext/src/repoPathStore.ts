/**
 * repoPathStore.ts
 *
 * Persists the repo_name + branch_name → local repo_path mapping across
 * VS Code sessions using globalState.
 *
 * This is necessary because the Potpie backend DB may not store repo_path
 * (or the project was parsed before that field was tracked).  We record the
 * mapping at parse time and look it up at wiki-generation time.
 */
import * as vscode from 'vscode';

const STORE_KEY = 'potpie.repoPathMap';

type RepoPathMap = Record<string, string>; // key = "repo_name:branch_name"

function storeKey(repoName: string, branchName: string): string {
  return `${repoName}:${branchName}`;
}

/** Persist a repo_name + branch_name → repo_path mapping. */
export function saveRepoPath(
  context: vscode.ExtensionContext,
  repoName: string,
  branchName: string,
  repoPath: string,
): void {
  const map = context.globalState.get<RepoPathMap>(STORE_KEY, {});
  map[storeKey(repoName, branchName)] = repoPath;
  context.globalState.update(STORE_KEY, map);
}

/**
 * Look up the repo_path for a given repo_name + branch_name.
 * Returns `undefined` when no mapping has been saved yet.
 */
export function lookupRepoPath(
  context: vscode.ExtensionContext,
  repoName: string,
  branchName: string,
): string | undefined {
  const map = context.globalState.get<RepoPathMap>(STORE_KEY, {});
  return map[storeKey(repoName, branchName)];
}
