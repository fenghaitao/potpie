# output

Handles the two final steps of the generation pipeline: computing where each documentation file should be written, and building the index that links everything together.

**Source:** `repowiki/output.py`

## Functions

### compute_output_path

Determines the output path for a generated documentation file by replacing the source extension with `.md` and placing the result under `output_dir`, preserving the original directory structure.

For example, `src/auth/user.py` with `output_dir = "docs"` produces `docs/src/auth/user.md`.

| Name | Type | Description | Default |
| ---- | ---- | ----------- | ------- |
| source_path | `str` | Relative path of the source file. | |
| output_dir | `str` | Root directory for all generated output. | |

**Returns:** The full output path as a string, ending in `.md`.

### build_index

Builds the index file linking to every generated module page. Modules are grouped by source directory and sorted alphabetically within each group.

The index filename depends on `output_style`: `"github-wiki"` produces `_Sidebar.md`; `"docs-folder"` produces `README.md`.

| Name | Type | Description | Default |
| ---- | ---- | ----------- | ------- |
| modules | `List[CodeModule]` | All successfully documented modules. | |
| output_dir | `str` | Root output directory for constructing the index path. | |
| output_style | `str` | Either `"github-wiki"` or `"docs-folder"`. | |

**Returns:** A tuple of `(index_content, index_filename)`.
