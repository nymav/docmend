# Report workspace validation — 3 November 2026

## Executed checks

- 12 Node tests passed: actual engine fixtures, status counts, symbol filtering,
  invalid schema/commit/path/range/hash rejection, diff display, actual `git apply`
  against temporary files, multiple-section patch offsets and final-newline
  handling, draft/overlap/hash conflicts, asset delivery and method restrictions.
- Browser: imported the engine's actual after-repair report using the file chooser;
  the library added it, selected it and showed one matching declaration and no
  repair. Source evidence displayed both exact function snapshots.
- Browser: finding search displayed its empty state, then restored the finding.
- First-use flow: one click opens the example, with both source snapshots and the
  documentation correction visible without switching tabs. The saved after-repair
  view shows a matching declaration and no repair. Returning home preserves the
  report library.
- Actual browser-downloaded patch was applied with Git in a temporary repository;
  its output exactly matched the engine's proposed documentation.
- New onboarding page checked at 390px and 1440px. Mobile viewport and document
  width both equal 390px; the report preview has no page-level horizontal overflow.
- Visual checks: 390px phone, 768px tablet and 1440px desktop layouts. Tablet
  document width equals viewport width (768px), without page-level overflow.
- No GitHub credentials, model requests, remote imports, third-party fonts,
  analytics or asset CDNs are used.

## Limits

This is a hosted report reviewer, not a production multi-tenant scanning service.
It has no live GitHub connection, persistent report storage, billing or repair PR
creation. Private hosting supplies the access boundary. Do not call the frontend
schema checks semantic revalidation: the engine must recheck source and file hashes.
Two bundled reports are constructed examples; they are explicitly labelled DEMO.
