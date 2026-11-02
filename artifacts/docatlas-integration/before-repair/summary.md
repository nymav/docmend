<!-- docmend-summary:v1 -->
## DocMend documentation check

Base `fa1e47ca0c7faf5c2fc7a4276ecf552ce9f33823` · Head `47d640296631a0308cf5249c0b8f7192a07f2b8b`

**changed units:** 1 | **stale:** 1 | **review:** 1 | **accurate:** 0 | **safe edits:** 1 | **draft edits:** 0 | **coverage gaps:** 0

| Document section | Status | Evidence | Diagnosis |
|---|---|---|---|
| README.md: DocAtlas &gt; Measured, not assumed | review | static | Changed code is linked to this section; semantic accuracy requires review |
| docs/docmend-integration-fixture.md: DocMend controlled integration fixture | stale | static | Documented call/default differs from the new AST contract |

### Analysis limits

- Offline mode: behavioural and ambiguous changes are review findings, not LLM-verified decisions

Safe edits are limited to explicit documented signatures/defaults/config literals. Model judgments and drafts require review. Confidence is not a calibrated correctness probability.
