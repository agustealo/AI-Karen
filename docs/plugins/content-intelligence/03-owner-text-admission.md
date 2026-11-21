# Content Intelligence: owner-active text admission (KCE-FREE-02B)

Internal host-only integration at `src/ai_karen_engine/extensions/content_intelligence_sources.py`.

The runtime supplies a typed, scope-bound `AuthorizedExecutionPlan`,
`ExtensionExecutionContext`, existing plugin kernel and canonical ArtifactStore.
Owner-active inert source text is retrieved using
`ArtifactStore.read_owner_active_code()`, whose repository implementation
must verify current owner, active state, content digest and safe text type.
The host additionally checks source revision and bound principal before
forwarding the bounded documents to the existing plugin execution gate.

No new route, file storage owner, plugin runtime or commercial dependency is
introduced. This does **not** support arbitrary PDF/DOCX files, authorize direct
reads inside the plugin, or establish consumer-ready UI behavior. It does not
publish a release copy to `free_plugins/`. Live authenticated first-boot/source
revocation acceptance, independent review and CI remain separate gates.

Proof: `pytest -q tests/extensions/test_content_intelligence_owner_sources.py`
and the existing Content Intelligence / ArtifactStore tests.
