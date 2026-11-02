<!-- docmend-summary:v1 -->
## DocMend documentation check

Base `fa1e47ca0c7faf5c2fc7a4276ecf552ce9f33823` · Head `47b9f2bf37c5093a5078e9c10a2badc9732b1b6e`

**changed units:** 1 | **stale:** 0 | **review:** 1 | **accurate:** 1 | **safe edits:** 0 | **draft edits:** 0 | **coverage gaps:** 0

| Document section | Status | Evidence | Diagnosis |
|---|---|---|---|
| README.md: DocAtlas &gt; Measured, not assumed | review | static | Changed code is linked to this section; semantic accuracy requires review |
| docs/docmend-integration-fixture.md: DocMend controlled integration fixture | accurate | static | Explicit documented signature/config literal matches the new contract; surrounding prose is not semantically certified |

### Analysis limits

- Offline mode: behavioural and ambiguous changes are review findings, not LLM-verified decisions

Safe edits are limited to explicit documented signatures/defaults/config literals. Model judgments and drafts require review. Confidence is not a calibrated correctness probability.
