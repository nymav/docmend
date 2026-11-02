"""Explicit GitHub publishing adapter. Recompute reports before calling this boundary."""
from __future__ import annotations

import json
import os
from urllib.error import HTTPError, URLError
from urllib.parse import quote, urlencode
from urllib.request import Request, build_opener

from .models import DocMendError, Report
from .provider import NoRedirect
from .repair import patched_files
from .reporting import markdown


class GitHub:
    def __init__(self, repository: str, token: str):
        import re
        if not re.fullmatch(r"[A-Za-z0-9_.-]+/[A-Za-z0-9_.-]+", repository) or not token:
            raise DocMendError("Expected owner/repository and a GitHub token")
        self.repository = repository
        self.token = token
        self.opener = build_opener(NoRedirect())

    def request(self, method: str, path: str, body: dict | None = None):
        route = "https://api.github.com/repos/" + self.repository + path
        req = Request(route, data=json.dumps(body).encode() if body is not None else None, method=method, headers={"Authorization": "Bearer " + self.token, "Accept": "application/vnd.github+json", "X-GitHub-Api-Version": "2026-03-10", "User-Agent": "docmend", "Content-Type": "application/json"})
        try:
            with self.opener.open(req, timeout=30) as response:
                raw = response.read(5_000_001)
                if len(raw) > 5_000_000:
                    raise DocMendError("GitHub response too large")
                return json.loads(raw)
        except HTTPError as exc:
            raise DocMendError(f"GitHub HTTP {exc.code}; no automatic retry of mutations") from exc
        except (URLError, TimeoutError, OSError, ValueError) as exc:
            raise DocMendError("GitHub transport or response error") from exc

    def comment(self, number: int, body: str) -> str:
        # Bounded pagination; update only bot-authored marker comments.
        for page in range(1, 11):
            comments = self.request("GET", f"/issues/{number}/comments?per_page=100&page={page}")
            if not isinstance(comments, list):
                raise DocMendError("Invalid comments response")
            for comment in comments:
                if comment.get("body", "").startswith("<!-- docmend-summary:v1 -->") and comment.get("user", {}).get("type") == "Bot":
                    return self.request("PATCH", f"/issues/comments/{int(comment['id'])}", {"body": body})["html_url"]
            if len(comments) < 100:
                break
        else:
            raise DocMendError("Comment scan limit exceeded; refusing a duplicate summary")
        return self.request("POST", f"/issues/{number}/comments", {"body": body})["html_url"]

    def publish(self, number: int, report: Report, files: dict[str, str], *, include_drafts: bool = False) -> dict:
        if type(number) is not int or number < 1:
            raise DocMendError("Invalid PR number")
        pull = self.request("GET", f"/pulls/{number}")
        if pull.get("state") != "open" or pull.get("head", {}).get("repo", {}).get("full_name") != self.repository or pull.get("base", {}).get("repo", {}).get("full_name") != self.repository:
            raise DocMendError("Publishing requires an open, same-repository PR; forks are read-only")
        if pull["head"]["sha"] != report.head or pull["base"]["sha"] != report.base:
            raise DocMendError("PR changed since analysis; recompute before publishing")
        updated = patched_files(files, report.edits, include_drafts=include_drafts)
        result = {"fix_pr": None, "summary": None}
        if updated:
            parent = self.request("GET", "/git/commits/" + report.head)
            tree = self.request("POST", "/git/trees", {"base_tree": parent["tree"]["sha"], "tree": [{"path": path, "mode": "100644", "type": "blob", "content": content} for path, content in sorted(updated.items())]})
            branch = f"docmend/pr-{number}-{report.head[:12]}"
            # Existing branches are never force-updated. Verify tree and parent on reruns.
            refs = self.request("GET", "/git/matching-refs/heads/" + quote(branch, safe="/"))
            exact = next((r for r in refs if r["ref"] == "refs/heads/" + branch), None)
            if exact:
                existing = self.request("GET", "/git/commits/" + exact["object"]["sha"])
                if existing["tree"]["sha"] != tree["sha"] or [p["sha"] for p in existing["parents"]] != [report.head]:
                    raise DocMendError("Existing repair branch differs; refusing to overwrite it")
            else:
                commit = self.request("POST", "/git/commits", {"message": f"docs: repair explicit drift for PR #{number}", "tree": tree["sha"], "parents": [report.head]})
                # Recheck head immediately before exposing the branch/PR.
                live = self.request("GET", f"/pulls/{number}")
                if live["head"]["sha"] != report.head or live["base"]["sha"] != report.base:
                    raise DocMendError("PR changed during publish; Git objects remain unreferenced")
                self.request("POST", "/git/refs", {"ref": "refs/heads/" + branch, "sha": commit["sha"]})
            query = urlencode({"state": "open", "head": self.repository.split('/')[0] + ":" + branch, "base": pull["head"]["ref"]})
            existing_prs = self.request("GET", "/pulls?" + query)
            if existing_prs:
                result["fix_pr"] = existing_prs[0]["html_url"]
            else:
                fix = self.request("POST", "/pulls", {"title": f"docs: documentation repairs for #{number}", "head": branch, "base": pull["head"]["ref"], "body": markdown(report), "draft": True})
                result["fix_pr"] = fix["html_url"]
        body = markdown(report)
        if result["fix_pr"]:
            body += "\nRepair draft PR: " + result["fix_pr"] + "\n"
        result["summary"] = self.comment(number, body)
        return result
