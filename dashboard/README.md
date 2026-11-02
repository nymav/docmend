# DocMend review workspace

A private, browser-based reviewer for DocMend schema-v1 reports. This version is
**report-import only**, as requested. It does not start scans, connect a GitHub
account, apply repairs or create pull requests.

## Use

The first screen offers **Open my report** and **Try a working example**.
Choose `report.json` from a DocMend CLI run or an extracted GitHub Actions
artifact, or drop the file onto the page. The workspace automatically opens the
first finding. Code evidence and the documentation correction appear together;
there are no detail tabs. Download the patch directly or export the original JSON.
A first-use disclosure explains where to obtain a report. The example includes a
one-click link to its saved recheck result, clearly distinguished from a live scan. Two clearly labelled
constructed demo reports show actual saved engine output before and after repair.

Files are read in browser memory. They are never uploaded, persisted in browser
storage or sent to an API. Reloading resets the report library. Maximum report size:
10 MB; at most 20 imports per selection and 30 reports per session.

The display reflects engine findings; importing a file is not independent evidence
validation. A “safe” label is a reported engine decision. Use DocMend's guarded CLI
apply command against the original checkout for hash and source verification.
Only safe proposals can be exported as patches; drafts remain visible for review.
Zero-context patches may require `git apply --unidiff-zero`; review all patches first.

Keyboard shortcuts: `/` focuses filtering, Escape clears it, Ctrl/Cmd+O opens import.
`j` and `k` select the next and previous visible findings. On-screen navigation
also supports reports with multiple findings. Status is communicated in words as
well as colour. Mobile stacks findings and detail; desktop uses a file navigator
and adjacent review panel. Tablet retains the report switcher.

## Develop

Node 22+; no npm dependencies or external asset services.

```sh
npm test
npm run dev
npm run build
npm run validate
```

The preview prints its loopback URL (default port 8792). `ui/` is the editable
source. `scripts/compile-ui.mjs` embeds those six files in `worker/index.js`.
The build packages this Worker using the Sites ESM starter's build script.
`.openai/hosting.json` identifies the private hosted Site. Source and browser code
contain no GitHub credentials. The deployed worker only serves a fixed asset map;
it has no upload, authentication-token or repository mutation endpoints.

See `VALIDATION.md` for the release checks and limits. MIT licensed, as part of
DocMend.
