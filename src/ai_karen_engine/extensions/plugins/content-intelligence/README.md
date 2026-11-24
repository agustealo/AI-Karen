# Content Intelligence (standalone plugin)

**Status:** v0.2.0 bounded stateless text-analysis slice. Governed investigation workspace with independent inventory admission. No persistent file or folder indexing, no live LlamaIndex dependency, no graph persistence, and no direct upload endpoint. These are not claimed as available.

The backend extension is located under `src/ai_karen_engine/extensions/plugins/content-intelligence/`. It implements the existing `ExtensionBase` contract, declares a closed invocation schema, and requests no memory, user-data, or network permissions. It does not alter Core.

Available operations: `analyze` (document fingerprints, term statistics and cross-document lexical relation hints), `search` (line-based lexical matches with source offsets), and `compare` (bounded lexical differences and Jaccard overlap). Search evidence includes exact start/end character offsets and content fingerprints. All data is supplied inline by an already authorized extension invocation. No file paths are accepted, no index is saved, and no external model is called.

See [developer wiki](../../../../../docs/plugins/content-intelligence/README.md) for security, architecture, contracts, limits, and the next gated integration slices.

## Shared explorer ownership

Browsing and selection reuse the controlled **File Explorer** presentation component. The Content Intelligence workspace requests its own authorized inventory endpoint; it does not require File Explorer activation. Content Intelligence only consumes explicitly authorized source content passed via its execution contract. Do not implement a second explorer or grant file access based on a caller-supplied folder label.
