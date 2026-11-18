"""Run stress cases and classify each outcome."""
from docmend.pipeline import analyze_files
from docmend.repair import patched_files


def outcome(case):
    try:
        report, _ = analyze_files(case["before"], case["after"])
    except Exception as exc:  # a crash is a result too
        return {"status": "error", "detail": f"{type(exc).__name__}: {exc}"}
    statuses = {f.status for f in report.findings if f.path == case["doc_path"]}
    edits = [e for e in report.edits if e.path == case["doc_path"]]
    result = {"status": "fixed" if edits else "review" if statuses & {"stale", "review"} else "quiet",
              "stale": "stale" in statuses, "codes": [c for f in report.findings for c in f.codes]}
    if edits:
        result["text"] = patched_files(case["after"], edits)[case["doc_path"]]
    return result


def violations(case, got):
    """Hard guarantees. Empty list means safe."""
    v = []
    if got["status"] == "error":
        v.append("crashed: " + got["detail"])
    if case["truth"] == "ok" and (got["status"] == "fixed" or got.get("stale")):
        v.append("edited or called stale a correct doc")
    if case["truth"] == "stale" and got["status"] == "quiet":
        v.append("missed a stale doc")
    if got["status"] == "fixed" and got.get("text") != case["gold"]:
        v.append("fix differs from gold")
    return v
