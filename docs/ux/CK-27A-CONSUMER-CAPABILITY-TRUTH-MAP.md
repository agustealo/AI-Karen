# CK-27A | Consumer capability truth map (initial source audit)

**Base:** main at `c54bca962f2a4dd167e8ef74d5c9298257e674d7` (PR #601).  
**Evidence level:** source inspection, not deployed or human browser acceptance.  
**Owner:** consumer UI for discovery and navigation; SessionProvider for identities; canonical Karen runtime for execution, policy, memory, tool eligibility and persistence.

## Method

Follow each consumer journey through **discover → invoke → authorized backend → observed result → persistence → recover**. A repository path proves presence, not correctness. Maintain the existing `docs/capabilities/baseline.v1.json` as the durable historical baseline; this document records the CK-27A *consumer surface* audit without creating an execution or provider registry. No numeric readiness score is asserted until executable browser evidence exists.

## Verified source topology

| User journey | Consumer entry point | Owner / boundary | Source-backed finding | Classification | Next proof |
|---|---|---|---|---|---|
| Ask Karen | Dashboard `chat` → `KarenCopilotConsumerChat` → `KarenCopilotChat` | CopilotKit UI; Karen runtime executes | Default dashboard route mounts the consumer adapter, not assistant-ui | Present, live unverified | Authenticated browser streamed turn + receipt |
| Saved conversations | Consumer chat controls, `SessionProvider` | SessionProvider canonical identity | New, search, select, rename and delete controls present | Present, live unverified | Rename/delete/switch while pending + reload |
| Real-model request | `KarenComposerRuntimeCatalog` | Runtime provider catalog and router | Provider requests derived from catalog; frontend disclaims selection authority | Present, live unverified | Requested vs actual model and fallback receipts |
| Registered agents | Catalog advanced view, dashboard `agents` | CORTEX policy; runtime action authorization | Catalog explicitly discovery-only; dashboard separately mounts `AgentsPage` | Journey split, execution unverified | Discover → eligible invoke → approval → receipt |
| Agent tasks | Dashboard `tasks` | Canonical automation/task APIs | `TasksPage` exists, but navigation is under collapsed Advanced tools | **Discovery friction evidenced** | First-time user navigation test |
| Jobs and scheduling | Dashboard `jobs`, `cronJobs` | Canonical scheduling services | Both rendered in dashboard, both under collapsed Advanced tools | Discovery friction, execution unverified | Create/change/cancel with persistence |
| Personas | Dashboard Persona Studio and chat selector | Persona service and preference store | Two discoverable entry points: Persona Studio and chat selector | Present, persistence unverified | Select/edit → reload → effective response |
| Settings | Dashboard `settings` and header Settings sheet | Settings panels own read/write | A complete settings shell exists in two placements | Present, contract unverified | Each setting read/write/reload/error |
| Plugins | Dashboard Tools & plugins and plugin routes | Plugin registry, manifests, RBAC | Overview in primary nav; injected plugin pages in Advanced tools | Split journey, eligibility unverified | Discover → authorize → run → disable |
| Context and memory | `KarenCopilotVerifiedRail`, `ConversationContextRail` | Runtime metadata and governed recall | Context rail has substantial presentation logic; no proof every card reflects authorized runtime facts | Investigation | Replay/degradation/tenant isolation |
| Voice capture | `KarenCopilotControlledChat` | Dictation ports and backend as supported | Local and browser dictation components imported | Present, browser unverified | Permission denied, transcription, draft recovery |
| Structured presentation | `KarenPresentationRegistry` | Versioned allowlisted envelope | Six types allowlisted: weather observation/comparison, planner task list, time/date observation, composition | **Bounded coverage** | Complete type matrix + stream/replay parity |
| Rich results | `RichResultWorkspace` | Existing presentation/artifact owners | Separate rich-result component exists; whether used by primary chat not established | Reachability unknown | Import graph and render contract |
| Messages/channels | Dashboard `commsCenter` | Comms services | Primary navigation mounts Comms Center | Present, integration unverified | Connected channel journey |
| Backend health | Dashboard fetches `/api/health` | Proxy and FastAPI readiness | Explicit retry + failure presentation | Present, live blocked by external config | Deployed readiness and recovery |

## Confirmed source-level concerns

1. **P1 consumer discoverability:** primary `Explore → Automations` leads to overview, while actual Agents, Tasks, Jobs, and Cron Jobs are behind `Advanced tools`. The navigation vocabulary fragments one user goal; validate whether a task-focused direct affordance belongs in the primary navigation or overview. Do not prematurely move admin-only controls into consumer nav.
2. **P1 capability-baseline staleness:** `docs/capabilities/baseline.v1.json` and its README still describe assistant-ui as the relevant AG-UI consumer integration even though `app/dashboard/page.tsx` mounts CopilotKit. Historical descriptions must be updated through existing verifier rules, not duplicated.
3. **P1 presentation coverage:** six types in the governed registry do not establish broad tables/charts/documents/approval rendering. Audit existing `RichResultWorkspace` and other renderers before implementing new ones.
4. **P1 split discovery/execution:** runtime catalog lists agents but expressly does not grant execution, while dashboard provides a separate Agents workspace. Prove the handoff and policy checks end to end.
5. **P0 evidence gap:** source CI success on PR #601 is not browser verification against running FastAPI. Render deployment remained unsuccessful at baseline. No consumer-ready claim is authorized.

## CK-27A execution order

1. Trace *active* dashboard routes and every primary/advanced action to its canonical API and permission checks.
2. Update stale entries in the existing capability baseline only after replacement-path evidence and verifier compatibility.
3. Fix demonstrated primary consumer navigation dead ends and terminology mismatches; prefer existing overview/action components.
4. Audit runtime presentation paths and collapse duplicate renderers only after usage and regression checks.
5. Automate accessibility, keyboard, focus, mobile overflow, refresh, cancellation, stale session, and authorization journeys.
6. Merge each focused slice after exact-head gates. External Render and Vercel configuration remains separately user-owned; real-host certification is explicitly withheld.

## Acceptance ledger

- **Source inspection**: dashboard navigation, consumer chat, provider catalog, settings shell, and presentation registry read at baseline.
- **Automated CK-27A tests**: not yet run.
- **Browser UX**: not yet run.
- **Hosted integration**: not yet run.
- **Release approval**: no.
