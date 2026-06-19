"""
GitHub REST API client.
All endpoints used here are public — no auth needed for public repos.
Optional GITHUB_TOKEN env var raises rate limit from 60 to 5000 req/hr.
"""

import base64
import os
from urllib.parse import urlparse

import httpx

GITHUB_API = "https://api.github.com"

PACKAGE_FILES = [
    "package.json",
    "requirements.txt",
    "pyproject.toml",
    "build.gradle",
    "build.gradle.kts",
    "pom.xml",
    "Cargo.toml",
    "go.mod",
    "pubspec.yaml",
    "Gemfile",
    "composer.json",
]


def _headers() -> dict:
    h = {
        "Accept": "application/vnd.github+json",
        "X-GitHub-Api-Version": "2022-11-28",
    }
    token = os.getenv("GITHUB_TOKEN")
    if token:
        h["Authorization"] = f"Bearer {token}"
    return h


def parse_github_url(url: str) -> tuple[str, str]:
    """Extract owner and repo name from a GitHub URL."""
    path = urlparse(url.rstrip("/")).path.strip("/")
    parts = path.split("/")
    if len(parts) < 2:
        raise ValueError(f"Could not parse GitHub URL: {url}")
    return parts[0], parts[1]


async def get_repo_metadata(owner: str, repo: str) -> dict:
    async with httpx.AsyncClient(timeout=15, follow_redirects=True) as client:
        r = await client.get(f"{GITHUB_API}/repos/{owner}/{repo}", headers=_headers())
        r.raise_for_status()
        d = r.json()
        return {
            "name": d["name"],
            "description": d.get("description") or "",
            "language": d.get("language") or "Unknown",
            "stars": d.get("stargazers_count", 0),
            "default_branch": d.get("default_branch", "main"),
            "topics": d.get("topics", []),
        }


async def get_file_tree(owner: str, repo: str, branch: str = "HEAD") -> list[dict]:
    """Returns the full recursive file tree from GitHub."""
    async with httpx.AsyncClient(timeout=30, follow_redirects=True) as client:
        r = await client.get(
            f"{GITHUB_API}/repos/{owner}/{repo}/git/trees/{branch}",
            params={"recursive": "1"},
            headers=_headers(),
        )
        r.raise_for_status()
        return r.json().get("tree", [])


async def get_readme(owner: str, repo: str) -> str:
    """Returns the decoded README text (first 3000 chars)."""
    async with httpx.AsyncClient(timeout=15, follow_redirects=True) as client:
        try:
            r = await client.get(
                f"{GITHUB_API}/repos/{owner}/{repo}/readme",
                headers=_headers(),
            )
            r.raise_for_status()
            raw = r.json().get("content", "")
            return base64.b64decode(raw).decode("utf-8", errors="replace")[:3000]
        except Exception:
            return ""


async def get_file_content(owner: str, repo: str, path: str) -> str:
    """Returns the decoded content of a single file (first 2000 chars)."""
    async with httpx.AsyncClient(timeout=15, follow_redirects=True) as client:
        try:
            r = await client.get(
                f"{GITHUB_API}/repos/{owner}/{repo}/contents/{path}",
                headers=_headers(),
            )
            r.raise_for_status()
            raw = r.json().get("content", "")
            return base64.b64decode(raw).decode("utf-8", errors="replace")[:2000]
        except Exception:
            return ""


def extract_folders(tree: list[dict], max_depth: int = 2) -> list[dict]:
    """Returns only the directory entries up to max_depth levels deep."""
    return [
        item
        for item in tree
        if item["type"] == "tree" and item["path"].count("/") < max_depth
    ]


def find_package_files(tree: list[dict]) -> list[str]:
    """Returns paths of any recognised package/build files found in the tree."""
    tree_paths = {item["path"] for item in tree}
    return [p for p in PACKAGE_FILES if p in tree_paths]
