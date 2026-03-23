/**
 * Global state for the Potpie extension.
 * Tracks the currently selected repository, branch, project ID, and local repo path.
 */
export interface PotpieState {
  currentRepo: string | undefined;
  currentBranch: string | undefined;
  currentProjectId: string | undefined;
  /** Absolute path to the user's repository on disk (used by DeepWikiGenerator). */
  currentRepoPath: string | undefined;
}

export const state: PotpieState = {
  currentRepo: undefined,
  currentBranch: undefined,
  currentProjectId: undefined,
  currentRepoPath: undefined,
};
