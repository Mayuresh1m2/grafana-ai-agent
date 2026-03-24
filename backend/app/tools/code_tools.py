"""Repository code reader, indexer, and error-source finder.

Provides two main classes:

``RepositoryReader``
    Thin async shell over ``git`` commands (subprocess via ``asyncio.to_thread``).
    Enforces path-traversal prevention and a 500 MB repo-size cap.

``CodeSearchEngine``
    Analyses error messages / stack traces to pinpoint source locations and
    optionally explain them via CodeLlama.

Security guarantees
-------------------
* All user-supplied file paths are resolved via ``Path.resolve()`` and
  checked to be strictly inside the repo root before any I/O occurs.
* Subprocess commands are built as ``list[str]`` — ``shell=False`` always.
* The ``pattern`` argument of ``search_pattern`` is treated as a fixed string
  (``git grep -F``) so regex metacharacters in error messages are safe.
* Repos larger than 500 MB are refused at construction time.
"""

from __future__ import annotations

import asyncio
import re
import subprocess
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

import structlog
from pydantic import BaseModel, Field

logger = structlog.get_logger(__name__)

# ---------------------------------------------------------------------------
# Constants
# ---------------------------------------------------------------------------

_MAX_FILE_LINES = 10_000
_MAX_REPO_BYTES = 500 * 1024 * 1024  # 500 MB

_EXCLUDED_DIRS = frozenset(
    {".git", "node_modules", "__pycache__", "dist", "build", ".mypy_cache",
     ".pytest_cache", ".tox", ".eggs", "*.egg-info"}
)
_EXCLUDED_EXTS = frozenset({".pyc", ".pyo", ".pyd", ".so", ".dylib"})

_LANG_MAP: dict[str, str] = {
    ".py": "python", ".ts": "typescript", ".js": "javascript",
    ".go": "go", ".rs": "rust", ".java": "java",
    ".yaml": "yaml", ".yml": "yaml", ".json": "json",
    ".md": "markdown", ".sh": "bash", ".html": "html",
    ".css": "css", ".sql": "sql", ".toml": "toml",
}


def _detect_language(filename: str) -> str:
    return _LANG_MAP.get(Path(filename).suffix.lower(), "")


# ---------------------------------------------------------------------------
# Exceptions
# ---------------------------------------------------------------------------


class RepoError(RuntimeError):
    """Base class for repository errors."""


class PathTraversalError(RepoError):
    """Raised when a path resolves outside the repository root."""


class RepoTooLargeError(RepoError):
    """Raised when the repository exceeds the size limit."""


class GitCommandError(RepoError):
    """Raised when a git subprocess exits with a non-zero code."""


# ---------------------------------------------------------------------------
# Pydantic models
# ---------------------------------------------------------------------------


class RepoConfig(BaseModel):
    """Configuration for a local git repository."""

    local_path: str
    language: str = "python"
    branch: str = "main"


class FileNode(BaseModel):
    """A node in the repository file tree (file or directory)."""

    name: str
    path: str  # relative to repo root
    is_dir: bool
    language: str = ""
    size_bytes: int = 0
    last_commit_time: datetime | None = None
    children: list[FileNode] = Field(default_factory=list)


# Required for Pydantic v2 recursive model
FileNode.model_rebuild()


class FileTree(BaseModel):
    """Snapshot of the repository source tree."""

    root: str
    nodes: list[FileNode]
    total_files: int
    generated_at: datetime = Field(
        default_factory=lambda: datetime.now(tz=timezone.utc)
    )


class FileContent(BaseModel):
    """Contents of a single file with line numbers."""

    path: str
    content: str  # each line prefixed: "   1: <line>"
    line_start: int = 1
    total_lines: int
    truncated: bool
    truncation_notice: str = ""


class SearchMatch(BaseModel):
    """A single git-grep match with surrounding context."""

    file_path: str
    line_number: int
    line: str
    context_before: list[str] = Field(default_factory=list)
    context_after: list[str] = Field(default_factory=list)


class GitCommit(BaseModel):
    """Metadata for a single git commit."""

    sha: str
    short_sha: str
    author_name: str
    author_email: str
    date: datetime
    message: str


class BlameLine(BaseModel):
    """A single annotated line from git blame."""

    line_number: int
    sha: str
    author: str
    date: datetime
    content: str


class CodeReference(BaseModel):
    """A source-code location relevant to an error."""

    repo_path: str
    file_path: str
    line_start: int
    line_end: int
    snippet: str
    relevance_score: float
    explanation: str | None = None
    last_modified_commit: GitCommit | None = None


class CodeExplanation(BaseModel):
    """LLM-generated explanation for a code region."""

    file_path: str
    line_start: int
    line_end: int
    snippet: str
    explanation: str
    error_context: str
    model_used: str


# ---------------------------------------------------------------------------
# RepositoryReader
# ---------------------------------------------------------------------------


class RepositoryReader:
    """Async interface over a local git repository."""

    def __init__(self, config: RepoConfig) -> None:
        root = Path(config.local_path).resolve()
        if not root.exists():
            raise RepoError(f"Repository path does not exist: {root}")
        if not root.is_dir():
            raise RepoError(f"Repository path is not a directory: {root}")

        # Validate git repo
        result = subprocess.run(
            ["git", "rev-parse", "--git-dir"],
            capture_output=True, text=True, cwd=str(root),
        )
        if result.returncode != 0:
            raise RepoError(f"Not a git repository: {root}")

        # Size guard (skips .git dir for speed)
        self._check_repo_size(root)

        self._root = root
        self._config = config
        self._log = logger.bind(repo=str(root))

    # ------------------------------------------------------------------
    # Public API
    # ------------------------------------------------------------------

    async def get_file_tree(self, max_depth: int = 4) -> FileTree:
        """Return a tree of source files up to *max_depth* levels deep.

        Excludes ``.git``, ``node_modules``, ``__pycache__``, ``*.pyc``,
        ``dist``, and ``build``.
        """
        raw = await self._git("ls-files", "--cached")
        all_paths = [p for p in raw.splitlines() if p.strip()]

        filtered: list[str] = []
        for p in all_paths:
            parts = Path(p).parts
            if any(part in _EXCLUDED_DIRS for part in parts):
                continue
            if any(p.endswith(ext) for ext in _EXCLUDED_EXTS):
                continue
            if len(parts) <= max_depth:
                filtered.append(p)

        commit_times = await self._get_file_commit_times()
        nodes = self._build_tree_nodes(filtered, commit_times)

        return FileTree(
            root=str(self._root),
            nodes=nodes,
            total_files=len(filtered),
        )

    async def read_file(self, path: str) -> FileContent:
        """Return file content with line numbers; truncates at 10 000 lines."""
        resolved = self._safe_path(path)
        if not resolved.is_file():
            raise RepoError(f"Not a file: {path!r}")

        raw = await asyncio.to_thread(
            resolved.read_text, encoding="utf-8", errors="replace"
        )
        all_lines = raw.splitlines()
        total_lines = len(all_lines)
        truncated = total_lines > _MAX_FILE_LINES
        displayed = all_lines[:_MAX_FILE_LINES] if truncated else all_lines

        numbered = "\n".join(
            f"{i + 1:6d}: {line}" for i, line in enumerate(displayed)
        )
        rel_path = str(resolved.relative_to(self._root))

        return FileContent(
            path=rel_path,
            content=numbered,
            line_start=1,
            total_lines=total_lines,
            truncated=truncated,
            truncation_notice=(
                f"File truncated at {_MAX_FILE_LINES} lines "
                f"(actual total: {total_lines} lines)."
                if truncated else ""
            ),
        )

    async def search_pattern(
        self,
        pattern: str,
        file_glob: str = "**/*.py",
        context_lines: int = 3,
    ) -> list[SearchMatch]:
        """Search the repo for *pattern* (literal, not regex) using git grep.

        Uses ``-F`` so regex special characters in error messages are safe.
        Returns matches with ``context_lines`` lines of surrounding context.
        """
        # Convert glob to pathspec understood by git grep
        # git grep uses -- <pathspec>; we pass the glob directly
        cmd = [
            "git", "grep",
            "--line-number",
            "-F",            # literal fixed-string search (no regex injection)
            "-e", pattern,
            "--",
            file_glob,
        ]
        result = await asyncio.to_thread(
            subprocess.run, cmd,
            capture_output=True, text=True, cwd=str(self._root),
        )
        if result.returncode == 1:
            return []  # no matches — normal for grep
        if result.returncode != 0:
            self._log.warning(
                "git_grep_error", stderr=result.stderr[:200], pattern=pattern[:60]
            )
            return []

        # Parse "filename:linenum:content"
        matches: list[SearchMatch] = []
        for raw_line in result.stdout.splitlines():
            parts = raw_line.split(":", 2)
            if len(parts) < 3:
                continue
            file_path, line_num_str, line_content = parts[0], parts[1], parts[2]
            try:
                line_num = int(line_num_str)
            except ValueError:
                continue

            context_b, context_a = await self._read_context(
                file_path, line_num, context_lines
            )
            matches.append(
                SearchMatch(
                    file_path=file_path,
                    line_number=line_num,
                    line=line_content,
                    context_before=context_b,
                    context_after=context_a,
                )
            )
        return matches

    async def get_git_log(
        self,
        path: str | None = None,
        n: int = 20,
    ) -> list[GitCommit]:
        """Return the *n* most recent commits, optionally scoped to *path*."""
        # Null-byte field delimiter — safe since commit messages don't contain NUL
        fmt = "%H%x00%h%x00%an%x00%ae%x00%aI%x00%s"
        cmd = ["git", "log", f"--format={fmt}", f"-{n}"]
        if path:
            safe = self._safe_path(path)
            rel = str(safe.relative_to(self._root))
            cmd += ["--", rel]

        raw = await self._git(*cmd[1:])  # _git prepends "git"
        commits: list[GitCommit] = []
        for line in raw.splitlines():
            if not line.strip():
                continue
            fields = line.split("\x00")
            if len(fields) < 6:
                continue
            sha, short_sha, author_name, author_email, date_str, message = fields[:6]
            try:
                date = datetime.fromisoformat(date_str)
            except ValueError:
                continue
            commits.append(
                GitCommit(
                    sha=sha,
                    short_sha=short_sha,
                    author_name=author_name,
                    author_email=author_email,
                    date=date,
                    message=message,
                )
            )
        return commits

    async def get_blame(
        self,
        file_path: str,
        line_start: int,
        line_end: int,
    ) -> list[BlameLine]:
        """Return blame information for lines *line_start*–*line_end*."""
        resolved = self._safe_path(file_path)
        rel = str(resolved.relative_to(self._root))
        raw = await self._git(
            "blame",
            f"-L{line_start},{line_end}",
            "--porcelain",
            rel,
        )
        return self._parse_blame_porcelain(raw)

    # ------------------------------------------------------------------
    # Security: path resolution
    # ------------------------------------------------------------------

    def _safe_path(self, path: str) -> Path:
        """Resolve *path* relative to repo root and assert no traversal.

        Raises
        ------
        PathTraversalError
            If the resolved path falls outside the repository root.
        """
        resolved = (self._root / path).resolve()
        try:
            resolved.relative_to(self._root)
        except ValueError:
            raise PathTraversalError(
                f"Path {path!r} resolves to {resolved}, which is outside "
                f"the repository root {self._root}."
            )
        return resolved

    # ------------------------------------------------------------------
    # Internal git helpers
    # ------------------------------------------------------------------

    async def _git(self, *args: str) -> str:
        """Run ``git <args>`` in the repo root and return stdout."""
        cmd = ["git", *args]
        result = await asyncio.to_thread(
            subprocess.run, cmd,
            capture_output=True, text=True, cwd=str(self._root),
        )
        # Many git commands return non-zero for benign reasons (no output, etc.)
        # Callers handle returncode themselves for grep; here we log warnings.
        if result.returncode != 0:
            self._log.debug(
                "git_nonzero", args=args[:3], stderr=result.stderr[:200]
            )
        return result.stdout

    async def _get_file_commit_times(self) -> dict[str, datetime]:
        """Return a dict mapping relative file path → last commit timestamp."""
        raw = await self._git(
            "log",
            "--pretty=format:COMMIT|%aI",
            "--name-only",
            "-n", "200",
        )
        times: dict[str, datetime] = {}
        current_ts: datetime | None = None
        for line in raw.splitlines():
            if line.startswith("COMMIT|"):
                try:
                    current_ts = datetime.fromisoformat(line[7:])
                except ValueError:
                    current_ts = None
            elif line.strip() and current_ts is not None:
                # Only record the first (most recent) commit for each file
                if line.strip() not in times:
                    times[line.strip()] = current_ts
        return times

    async def _read_context(
        self, file_path: str, line_num: int, context: int
    ) -> tuple[list[str], list[str]]:
        """Return *context* lines before and after *line_num* in *file_path*."""
        try:
            full = self._safe_path(file_path)
            raw = await asyncio.to_thread(
                full.read_text, encoding="utf-8", errors="replace"
            )
            lines = raw.splitlines()
            before = lines[max(0, line_num - 1 - context): line_num - 1]
            after = lines[line_num: line_num + context]
            return before, after
        except Exception:  # noqa: BLE001
            return [], []

    @staticmethod
    def _parse_blame_porcelain(output: str) -> list[BlameLine]:
        """Parse ``git blame --porcelain`` output into ``BlameLine`` objects."""
        lines = output.splitlines()
        blame: list[BlameLine] = []
        sha = ""
        author = ""
        author_ts = 0
        final_line = 0

        sha_re = re.compile(r"^([0-9a-f]{40}) \d+ (\d+)")

        for line in lines:
            m = sha_re.match(line)
            if m:
                sha = m.group(1)[:8]
                final_line = int(m.group(2))
            elif line.startswith("author ") and not line.startswith("author-"):
                author = line[7:]
            elif line.startswith("author-time "):
                try:
                    author_ts = int(line[12:])
                except ValueError:
                    author_ts = 0
            elif line.startswith("\t"):
                blame.append(
                    BlameLine(
                        line_number=final_line,
                        sha=sha,
                        author=author,
                        date=datetime.fromtimestamp(author_ts, tz=timezone.utc),
                        content=line[1:],  # strip leading tab
                    )
                )
        return blame

    def _build_tree_nodes(
        self,
        flat_paths: list[str],
        commit_times: dict[str, datetime],
    ) -> list[FileNode]:
        """Build a recursive ``FileNode`` tree from a flat list of paths."""
        # nested dict: dirs are dicts, files are the full path string
        nested: dict[str, Any] = {}
        for p in flat_paths:
            node: dict[str, Any] = nested
            parts = Path(p).parts
            for part in parts[:-1]:
                node = node.setdefault(part, {})
            node[parts[-1]] = p  # leaf → full relative path string

        def to_nodes(d: dict[str, Any], prefix: str) -> list[FileNode]:
            result: list[FileNode] = []
            for name, value in sorted(d.items()):
                rel = f"{prefix}/{name}".lstrip("/") if prefix else name
                if isinstance(value, dict):
                    result.append(
                        FileNode(
                            name=name,
                            path=rel,
                            is_dir=True,
                            children=to_nodes(value, rel),
                        )
                    )
                else:
                    full = self._root / value
                    try:
                        size = full.stat().st_size
                    except OSError:
                        size = 0
                    result.append(
                        FileNode(
                            name=name,
                            path=value,
                            is_dir=False,
                            language=_detect_language(name),
                            size_bytes=size,
                            last_commit_time=commit_times.get(value),
                        )
                    )
            return result

        return to_nodes(nested, "")

    @staticmethod
    def _check_repo_size(root: Path) -> None:
        """Raise ``RepoTooLargeError`` if source tree exceeds 500 MB."""
        total = 0
        for dirpath, dirnames, filenames in _os_walk(root):
            # Prune .git in-place to avoid counting pack objects
            if hasattr(dirnames, "remove"):
                try:
                    dirnames.remove(".git")
                except ValueError:
                    pass
            for fname in filenames:
                try:
                    total += Path(dirpath, fname).stat().st_size
                except OSError:
                    pass
                if total > _MAX_REPO_BYTES:
                    raise RepoTooLargeError(
                        f"Repository source tree exceeds "
                        f"{_MAX_REPO_BYTES // (1024 ** 2)} MB size limit."
                    )


def _os_walk(root: Path):  # type: ignore[return]
    """Compatibility shim for Python < 3.12 (Path.walk not available)."""
    import os
    for dirpath, dirnames, filenames in os.walk(str(root)):
        yield Path(dirpath), dirnames, filenames


# ---------------------------------------------------------------------------
# CodeSearchEngine
# ---------------------------------------------------------------------------

_TRACEBACK_FILE_RE = re.compile(r'File "([^"]+)", line (\d+), in (\S+)')
_EXCEPTION_TYPE_RE = re.compile(r'\b(\w+(?:Error|Exception|Warning|Fault))\b')
_CAMELCASE_RE = re.compile(r'\b([A-Z][a-zA-Z0-9]{2,})\b')
_FUNCTION_IN_TRACE_RE = re.compile(r'in ([a-z_][a-zA-Z0-9_]{2,})\b')
_IDENTIFIER_RE = re.compile(r'\b([a-z_][a-zA-Z0-9_]{3,})\b')


class CodeSearchEngine:
    """Locate and explain source code relevant to a production error."""

    def __init__(self, ollama_client: Any | None = None) -> None:
        """
        Args:
            ollama_client: Optional ``OllamaClient`` used for ``explain_code``.
                           If ``None``, ``explain_code`` returns a placeholder.
        """
        self._ollama = ollama_client

    # ------------------------------------------------------------------
    # Public API
    # ------------------------------------------------------------------

    async def find_error_source(
        self,
        error_message: str,
        stack_trace: str | None,
        repo: RepositoryReader,
    ) -> list[CodeReference]:
        """Locate the top 5 source locations most likely related to *error_message*.

        Strategy
        --------
        1. Extract class names, function names, and file stems from the error
           message and stack trace.
        2. Search each term via ``repo.search_pattern``.
        3. Score matches: traceback-file boost +2, exact-word-match +0.5,
           recent-commit +0.5.
        4. Return the top 5 ``CodeReference`` objects, highest score first.
        """
        terms = self._extract_terms(error_message, stack_trace)
        traceback_files = self._extract_traceback_files(stack_trace)

        if not terms:
            return []

        # Cap to 10 search terms to avoid excessive subprocess calls
        search_coros = [
            repo.search_pattern(term, "**/*.py") for term in terms[:10]
        ]
        raw_results = await asyncio.gather(*search_coros, return_exceptions=True)

        # Score: (file, line) → (SearchMatch, float)
        scored: dict[tuple[str, int], tuple[SearchMatch, float]] = {}
        for term, result in zip(terms[:10], raw_results):
            if isinstance(result, Exception):
                continue
            for match in result:
                key = (match.file_path, match.line_number)
                score = self._score_match(match, term, traceback_files, error_message)
                if key not in scored or scored[key][1] < score:
                    scored[key] = (match, score)

        top = sorted(scored.values(), key=lambda x: x[1], reverse=True)[:5]

        references: list[CodeReference] = []
        for match, score in top:
            snippet = await self._fetch_snippet(repo, match.file_path, match.line_number)

            # Boost score based on commit recency
            try:
                commits = await repo.get_git_log(path=match.file_path, n=1)
                last_commit: GitCommit | None = commits[0] if commits else None
                if last_commit:
                    days_old = (datetime.now(tz=timezone.utc) - last_commit.date).days
                    if days_old < 7:
                        score += 0.5
                    elif days_old < 30:
                        score += 0.25
            except Exception:  # noqa: BLE001
                last_commit = None

            references.append(
                CodeReference(
                    repo_path=str(repo._root),
                    file_path=match.file_path,
                    line_start=max(1, match.line_number - 5),
                    line_end=match.line_number + 5,
                    snippet=snippet,
                    relevance_score=round(score, 3),
                    last_modified_commit=last_commit,
                )
            )

        return references

    async def explain_code(
        self,
        file_path: str,
        line_start: int,
        line_end: int,
        error_context: str,
        repo: RepositoryReader,
    ) -> CodeExplanation:
        """Ask CodeLlama to explain a code region in the context of an error.

        If no ``OllamaClient`` was provided at construction time, the
        explanation field contains a placeholder string.
        """
        content = await repo.read_file(file_path)
        all_lines = content.content.splitlines()
        # Extract just the requested line range (line numbers are in "   N: ..." format)
        snippet_lines = [
            ln for ln in all_lines
            if _line_num_from_numbered(ln) in range(line_start, line_end + 1)
        ]
        snippet = "\n".join(snippet_lines) if snippet_lines else content.content[:2000]

        prompt = self.build_explain_prompt(
            file_path=file_path,
            line_start=line_start,
            line_end=line_end,
            snippet=snippet,
            error_context=error_context,
        )

        explanation = ""
        model_used = "none"

        if self._ollama is not None:
            try:
                from app.llm.client import OllamaMessage, OllamaModel

                chunks: list[str] = []
                gen = await self._ollama.chat(
                    [OllamaMessage(role="user", content=prompt)],
                    model=OllamaModel.CODELLAMA_7B,
                    temperature=0.2,
                )
                async for chunk in gen:
                    chunks.append(chunk)
                explanation = "".join(chunks).strip()
                model_used = OllamaModel.CODELLAMA_7B.value
            except Exception as exc:  # noqa: BLE001
                explanation = f"[LLM unavailable: {exc}]"
        else:
            explanation = "[No LLM client configured — call with an OllamaClient instance]"

        return CodeExplanation(
            file_path=file_path,
            line_start=line_start,
            line_end=line_end,
            snippet=snippet,
            explanation=explanation,
            error_context=error_context,
            model_used=model_used,
        )

    # ------------------------------------------------------------------
    # Prompt construction (public for testing)
    # ------------------------------------------------------------------

    @staticmethod
    def build_explain_prompt(
        file_path: str,
        line_start: int,
        line_end: int,
        snippet: str,
        error_context: str,
    ) -> str:
        """Return the CodeLlama prompt for a code explanation request.

        Extracted as a static method so tests can verify the prompt content
        without running the LLM.
        """
        return (
            "You are an expert Python developer reviewing a production bug.\n\n"
            f"Error context:\n{error_context}\n\n"
            f"Code from `{file_path}` (lines {line_start}–{line_end}):\n"
            "```python\n"
            f"{snippet}\n"
            "```\n\n"
            "Answer in 3–5 sentences:\n"
            "1. What does this code do?\n"
            "2. Why might it cause the error described above?\n"
            "3. What is the most likely fix?"
        )


    # ------------------------------------------------------------------
    # Term extraction helpers
    # ------------------------------------------------------------------

    @staticmethod
    def _extract_terms(error_message: str, stack_trace: str | None) -> list[str]:
        """Return ranked search terms extracted from *error_message* and *stack_trace*."""
        seen: set[str] = set()
        terms: list[str] = []

        def add(t: str) -> None:
            t = t.strip()
            if t and t not in seen and len(t) >= 3:
                seen.add(t)
                terms.append(t)

        # 1. Exception type (highest priority)
        for m in _EXCEPTION_TYPE_RE.finditer(error_message):
            add(m.group(1))

        # 2. Traceback: function names and file stems
        if stack_trace:
            for m in _TRACEBACK_FILE_RE.finditer(stack_trace):
                add(Path(m.group(1)).stem)      # file stem, e.g. "app"
                add(m.group(3))                 # function name

        # 3. CamelCase identifiers (class names)
        for m in _CAMELCASE_RE.finditer(error_message):
            add(m.group(1))

        # 4. Snake_case function names from traceback
        if stack_trace:
            for m in _FUNCTION_IN_TRACE_RE.finditer(stack_trace):
                name = m.group(1)
                if name not in ("module",):
                    add(name)

        # 5. Meaningful identifiers from the error detail text (last resort)
        colon_pos = error_message.find(":")
        if colon_pos != -1:
            detail = error_message[colon_pos + 1:].strip()
            for m in _IDENTIFIER_RE.finditer(detail):
                add(m.group(1))

        return terms

    @staticmethod
    def _extract_traceback_files(stack_trace: str | None) -> set[str]:
        """Return the set of file paths mentioned in *stack_trace*."""
        if not stack_trace:
            return set()
        return {
            m.group(1)
            for m in _TRACEBACK_FILE_RE.finditer(stack_trace)
        }

    @staticmethod
    def _score_match(
        match: SearchMatch,
        search_term: str,
        traceback_files: set[str],
        error_message: str,
    ) -> float:
        score = 0.5

        # Exact whole-word match in the matched line
        if re.search(rf"\b{re.escape(search_term)}\b", match.line):
            score += 0.5

        # File is mentioned in the traceback
        for tb_file in traceback_files:
            if (
                tb_file in match.file_path
                or Path(tb_file).stem in match.file_path
                or match.file_path in tb_file
            ):
                score += 2.0
                break

        # The error message itself mentions the file name
        if Path(match.file_path).stem in error_message:
            score += 0.5

        return score

    @staticmethod
    async def _fetch_snippet(
        repo: RepositoryReader, file_path: str, line_num: int, context: int = 5
    ) -> str:
        """Return a code snippet centred on *line_num* with ±*context* lines."""
        try:
            content = await repo.read_file(file_path)
            lines = content.content.splitlines()
            lo = max(0, line_num - context - 1)
            hi = line_num + context
            return "\n".join(lines[lo:hi])
        except Exception:  # noqa: BLE001
            return ""


def _line_num_from_numbered(line: str) -> int:
    """Parse the line number from a ``read_file`` numbered line like ``"   7: code"``."""
    try:
        return int(line.split(":", 1)[0].strip())
    except (ValueError, IndexError):
        return -1
