"""The little bit of the GitHub REST API the sync needs: read a file, push a
change on a branch, open a pull request. Token is a fine-grained PAT with
contents and pull-requests write on this one repo. The deploy workflow merges
the PR once the tests pass, so the Lambda never merges anything itself."""
from __future__ import annotations

import base64

API = "https://api.github.com"


class GitHubError(RuntimeError):
    pass


class GitHub:
    def __init__(self, http, token: str, repo: str, *, api: str = API):
        self.http = http
        self.repo = repo
        self.api = api
        self.headers = {
            "Authorization": f"Bearer {token}",
            "Accept": "application/vnd.github+json",
            "X-GitHub-Api-Version": "2022-11-28",
        }

    # -- reads ---------------------------------------------------------------

    def get_file(self, path: str, ref: str) -> tuple[str | None, str | None]:
        """(decoded text, blob sha) or (None, None) when the file does not exist."""
        r = self._req("GET", f"/repos/{self.repo}/contents/{path}", params={"ref": ref})
        if r.status_code == 404:
            return None, None
        data = self._ok(r)
        raw = base64.b64decode(data.get("content", "")).decode("utf-8")
        return raw, data.get("sha")

    def branch_sha(self, branch: str) -> str | None:
        r = self._req("GET", f"/repos/{self.repo}/git/ref/heads/{branch}")
        if r.status_code == 404:
            return None
        return self._ok(r)["object"]["sha"]

    def open_pr_for(self, head: str) -> str | None:
        owner = self.repo.split("/")[0]
        r = self._req("GET", f"/repos/{self.repo}/pulls", params={"state": "open", "head": f"{owner}:{head}"})
        prs = self._ok(r)
        return prs[0]["html_url"] if prs else None

    # -- writes --------------------------------------------------------------

    def ensure_branch(self, branch: str, base: str) -> None:
        if self.branch_sha(branch):
            return
        self.reset_branch(branch, base)

    def reset_branch(self, branch: str, base: str) -> None:
        """Point the branch at the tip of base, creating it if needed. Used when
        no PR is open, so a leftover branch from a merged or closed PR does not
        carry stale commits into the next one."""
        base_sha = self.branch_sha(base)
        if not base_sha:
            raise GitHubError(f"base branch {base!r} not found in {self.repo}")
        if self.branch_sha(branch):
            r = self._req("PATCH", f"/repos/{self.repo}/git/refs/heads/{branch}", json={"sha": base_sha, "force": True})
        else:
            r = self._req("POST", f"/repos/{self.repo}/git/refs", json={"ref": f"refs/heads/{branch}", "sha": base_sha})
        self._ok(r)

    def put_file(self, path: str, text: str, message: str, branch: str) -> str:
        """Create or update the file on the branch. Returns the commit sha."""
        _, sha = self.get_file(path, branch)
        body = {
            "message": message,
            "content": base64.b64encode(text.encode("utf-8")).decode("ascii"),
            "branch": branch,
        }
        if sha:
            body["sha"] = sha
        r = self._req("PUT", f"/repos/{self.repo}/contents/{path}", json=body)
        return self._ok(r)["commit"]["sha"]

    def create_pr(self, head: str, base: str, title: str, body: str) -> str:
        r = self._req(
            "POST", f"/repos/{self.repo}/pulls", json={"title": title, "head": head, "base": base, "body": body}
        )
        return self._ok(r)["html_url"]

    # -- plumbing ------------------------------------------------------------

    def _req(self, method: str, path: str, **kw):
        return self.http.request(method, self.api + path, headers=self.headers, timeout=30, **kw)

    @staticmethod
    def _ok(resp):
        if resp.status_code >= 400:
            raise GitHubError(f"GitHub {resp.status_code}: {resp.text[:300]}")
        return resp.json()
