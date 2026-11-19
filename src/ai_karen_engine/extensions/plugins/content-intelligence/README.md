# Content Intelligence (standalone plugin)

**Status:** v0.2.0 bounded stateless text-analysis slice. No persistent file or folder indexing, no UI, no live LlamaIndex dependency, no graph persistence, and no direct upload endpoint. These are not claimed as available.

This extension is located entirely under `src/ai_karen_engine/extensions/plugins/content-intelligence/`. It implements the existing `ExtensionBase` contract, declares a closed invocation schema, and requests no memory, user-data, or network permissions. It does not alter Core.

Available operations: `browse` (group already-authorized inline documents by opaque logical folder labels), `analyze` (document fingerprints, term statistics and cross-document lexical relation hints), `search` (line-based lexical matches with source offsets), and `compare` (bounded lexical differences and Jaccard overlap). Folder labels are organizational grouping hints, never ACLs. Search evidence includes exact start/end character offsets and content fingerprints. All data is supplied inline by an already authorized extension invocation. No file paths are accepted, no index is saved, and no external model is called.

See [developer wiki](../../../../../docs/plugins/content-intelligence/README.md) for security, architecture, contracts, limits, and the next gated integration slices.
