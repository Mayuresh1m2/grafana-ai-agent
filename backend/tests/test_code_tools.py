"""Tests for app.tools.code_tools — RepositoryReader and CodeSearchEngine."""

from __future__ import annotations

import subprocess
from pathlib import Path

import pytest

from app.tools.code_tools import (
    CodeReference,
    CodeSearchEngine,
    FileTree,
    GitCommit,
    PathTraversalError,
    RepoConfig,
    RepoError,
    RepoTooLargeError,
    RepositoryReader,
    _detect_language,
    _line_num_from_numbered,
)


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _reader(repo_path: Path) -> RepositoryReader:
    return RepositoryReader(RepoConfig(local_path=str(repo_path)))


# ---------------------------------------------------------------------------
# 1. RepositoryReader construction — validation
# ---------------------------------------------------------------------------


class TestRepositoryReaderConstruction:
    def test_valid_repo_constructed(self, sample_repo: Path) -> None:
        reader = _reader(sample_repo)
        assert reader._root == sample_repo.resolve()

    def test_nonexistent_path_raises(self, tmp_path: Path) -> None:
        with pytest.raises(RepoError, match="does not exist"):
            RepositoryReader(RepoConfig(local_path=str(tmp_path / "no_such_dir")))

    def test_non_git_directory_raises(self, tmp_path: Path) -> None:
        (tmp_path / "file.py").write_text("x = 1")
        with pytest.raises(RepoError, match="Not a git repository"):
            RepositoryReader(RepoConfig(local_path=str(tmp_path)))


# ---------------------------------------------------------------------------
# 2. Path traversal prevention
# ---------------------------------------------------------------------------


class TestPathTraversalPrevention:
    async def test_relative_traversal_blocked(self, sample_repo: Path) -> None:
        reader = _reader(sample_repo)
        with pytest.raises(PathTraversalError):
            await reader.read_file("../../etc/passwd")

    async def test_absolute_path_outside_repo_blocked(self, sample_repo: Path) -> None:
        reader = _reader(sample_repo)
        with pytest.raises(PathTraversalError):
            await reader.read_file("/etc/passwd")

    async def test_encoded_traversal_blocked(self, sample_repo: Path) -> None:
        reader = _reader(sample_repo)
        # Even after normalization this should still be outside
        with pytest.raises(PathTraversalError):
            await reader.read_file("api/../../../../../../etc/hosts")

    async def test_valid_path_within_repo_allowed(self, sample_repo: Path) -> None:
        reader = _reader(sample_repo)
        content = await reader.read_file("config.py")
        assert "get_config_value" in content.content

    async def test_nested_valid_path_allowed(self, sample_repo: Path) -> None:
        reader = _reader(sample_repo)
        content = await reader.read_file("api/app.py")
        assert "calculate_stats" in content.content

    def test_safe_path_resolves_correctly(self, sample_repo: Path) -> None:
        reader = _reader(sample_repo)
        resolved = reader._safe_path("api/app.py")
        assert resolved == (sample_repo / "api" / "app.py").resolve()

    async def test_get_blame_traversal_blocked(self, sample_repo: Path) -> None:
        reader = _reader(sample_repo)
        with pytest.raises(PathTraversalError):
            await reader.get_blame("../../etc/passwd", 1, 5)

    async def test_get_git_log_traversal_blocked(self, sample_repo: Path) -> None:
        reader = _reader(sample_repo)
        with pytest.raises(PathTraversalError):
            await reader.get_git_log(path="../../etc/passwd")


# ---------------------------------------------------------------------------
# 3. File tree
# ---------------------------------------------------------------------------


class TestGetFileTree:
    async def test_returns_file_tree(self, sample_repo: Path) -> None:
        reader = _reader(sample_repo)
        tree = await reader.get_file_tree()
        assert isinstance(tree, FileTree)
        assert tree.total_files > 0

    async def test_contains_known_files(self, sample_repo: Path) -> None:
        reader = _reader(sample_repo)
        tree = await reader.get_file_tree()
        all_paths = _collect_paths(tree.nodes)
        assert any("app.py" in p for p in all_paths)
        assert any("config.py" in p for p in all_paths)
        assert any("user.py" in p for p in all_paths)

    async def test_nested_structure_preserved(self, sample_repo: Path) -> None:
        reader = _reader(sample_repo)
        tree = await reader.get_file_tree()
        # Top-level should contain the api/ and models/ and utils/ dirs
        top_names = {n.name for n in tree.nodes}
        assert "api" in top_names or any("api" in p for p in _collect_paths(tree.nodes))

    async def test_pyc_files_excluded(self, sample_repo: Path) -> None:
        # Create a .pyc file and verify it's excluded
        pyc = sample_repo / "api" / "__pycache__" / "app.cpython-311.pyc"
        pyc.parent.mkdir(exist_ok=True)
        pyc.write_bytes(b"\x00")
        # Re-add to git would be needed for ls-files, but the filter should exclude it anyway
        reader = _reader(sample_repo)
        tree = await reader.get_file_tree()
        all_paths = _collect_paths(tree.nodes)
        assert not any(p.endswith(".pyc") for p in all_paths)

    async def test_max_depth_respected(self, sample_repo: Path) -> None:
        reader = _reader(sample_repo)
        tree_depth1 = await reader.get_file_tree(max_depth=1)
        tree_depth4 = await reader.get_file_tree(max_depth=4)
        # Depth-1 should include fewer files than depth-4
        assert tree_depth1.total_files <= tree_depth4.total_files

    async def test_language_annotated(self, sample_repo: Path) -> None:
        reader = _reader(sample_repo)
        tree = await reader.get_file_tree()
        py_files = [n for n in _collect_nodes(tree.nodes) if not n.is_dir and n.name.endswith(".py")]
        assert all(n.language == "python" for n in py_files)

    async def test_size_bytes_populated(self, sample_repo: Path) -> None:
        reader = _reader(sample_repo)
        tree = await reader.get_file_tree()
        files = [n for n in _collect_nodes(tree.nodes) if not n.is_dir]
        assert all(n.size_bytes >= 0 for n in files)
        # At least one file should be non-zero
        assert any(n.size_bytes > 0 for n in files)


# ---------------------------------------------------------------------------
# 4. read_file
# ---------------------------------------------------------------------------


class TestReadFile:
    async def test_reads_known_content(self, sample_repo: Path) -> None:
        reader = _reader(sample_repo)
        content = await reader.read_file("api/app.py")
        assert "ZeroDivisionError" in content.content
        assert not content.truncated

    async def test_line_numbers_present(self, sample_repo: Path) -> None:
        reader = _reader(sample_repo)
        content = await reader.read_file("config.py")
        first_line = content.content.splitlines()[0]
        # Should start with a line number like "     1: ..."
        assert first_line.strip().startswith("1:")

    async def test_total_lines_accurate(self, sample_repo: Path) -> None:
        reader = _reader(sample_repo)
        content = await reader.read_file("config.py")
        actual = len((sample_repo / "config.py").read_text().splitlines())
        assert content.total_lines == actual

    async def test_not_a_file_raises(self, sample_repo: Path) -> None:
        reader = _reader(sample_repo)
        with pytest.raises(RepoError):
            await reader.read_file("api")  # directory, not a file

    async def test_truncation_at_10k_lines(self, sample_repo: Path, tmp_path: Path) -> None:
        # Create a temp git repo with a huge file
        big_repo = tmp_path / "big_repo"
        big_repo.mkdir()
        subprocess.run(["git", "init"], cwd=str(big_repo), capture_output=True)
        subprocess.run(["git", "config", "user.email", "t@t.com"], cwd=str(big_repo), capture_output=True)
        subprocess.run(["git", "config", "user.name", "T"], cwd=str(big_repo), capture_output=True)
        subprocess.run(["git", "config", "commit.gpgsign", "false"], cwd=str(big_repo), capture_output=True)
        big_file = big_repo / "big.py"
        big_file.write_text("\n".join(f"x = {i}" for i in range(15_000)))
        subprocess.run(["git", "add", "."], cwd=str(big_repo), capture_output=True)
        subprocess.run(["git", "commit", "-m", "big"], cwd=str(big_repo), capture_output=True)

        reader = RepositoryReader(RepoConfig(local_path=str(big_repo)))
        content = await reader.read_file("big.py")
        assert content.truncated
        assert content.total_lines == 15_000
        assert "truncated" in content.truncation_notice
        # Content should only have 10k lines
        assert len(content.content.splitlines()) == 10_000


# ---------------------------------------------------------------------------
# 5. search_pattern — including regex special characters
# ---------------------------------------------------------------------------


class TestSearchPattern:
    async def test_finds_known_pattern(self, sample_repo: Path) -> None:
        reader = _reader(sample_repo)
        matches = await reader.search_pattern("ZeroDivisionError")
        assert len(matches) >= 1
        assert any("app.py" in m.file_path for m in matches)

    async def test_regex_special_chars_safe(self, sample_repo: Path) -> None:
        """Error messages containing [, ], ., * must not crash or inject regex."""
        reader = _reader(sample_repo)
        # These should simply find no matches (or matches if the literal text exists)
        # — but must NOT raise or crash
        for pattern in ["[Error]", "*.py", "func()", "price: $0.00", "a+b=c"]:
            matches = await reader.search_pattern(pattern)
            assert isinstance(matches, list)

    async def test_returns_empty_for_no_match(self, sample_repo: Path) -> None:
        reader = _reader(sample_repo)
        matches = await reader.search_pattern("xXxTHISPATTERNDOESNOTEXISTxXx")
        assert matches == []

    async def test_context_lines_populated(self, sample_repo: Path) -> None:
        reader = _reader(sample_repo)
        matches = await reader.search_pattern("ZeroDivisionError", context_lines=3)
        for m in matches:
            # Each match should have at most 3 context lines on each side
            assert len(m.context_before) <= 3
            assert len(m.context_after) <= 3

    async def test_glob_filter_restricts_files(self, sample_repo: Path) -> None:
        reader = _reader(sample_repo)
        # Search only in utils/
        matches_py = await reader.search_pattern("BUG", "**/*.py")
        matches_txt = await reader.search_pattern("BUG", "**/*.txt")
        # There should be BUG comments in .py files
        assert len(matches_py) >= 1
        # requirements.txt has no BUG comments
        assert len(matches_txt) == 0

    async def test_line_numbers_correct(self, sample_repo: Path) -> None:
        reader = _reader(sample_repo)
        matches = await reader.search_pattern("get_config_value")
        for m in matches:
            assert m.line_number >= 1

    async def test_backslash_in_pattern_safe(self, sample_repo: Path) -> None:
        reader = _reader(sample_repo)
        matches = await reader.search_pattern("path\\to\\file")
        assert isinstance(matches, list)

    async def test_double_quote_in_pattern_safe(self, sample_repo: Path) -> None:
        reader = _reader(sample_repo)
        # Double quotes appear in Python strings — should not break git grep
        matches = await reader.search_pattern('"user_id"')
        assert isinstance(matches, list)


# ---------------------------------------------------------------------------
# 6. get_git_log
# ---------------------------------------------------------------------------


class TestGetGitLog:
    async def test_returns_commits(self, sample_repo: Path) -> None:
        reader = _reader(sample_repo)
        commits = await reader.get_git_log()
        assert len(commits) >= 2  # fixture creates 2 commits

    async def test_commit_fields_populated(self, sample_repo: Path) -> None:
        reader = _reader(sample_repo)
        commits = await reader.get_git_log(n=1)
        c = commits[0]
        assert len(c.sha) == 40
        assert len(c.short_sha) <= 10
        assert "@" in c.author_email
        assert c.message

    async def test_file_scoped_log(self, sample_repo: Path) -> None:
        reader = _reader(sample_repo)
        # config.py was modified in the second commit
        commits = await reader.get_git_log(path="config.py")
        assert len(commits) >= 1
        assert any("TODO" in c.message or "missing" in c.message for c in commits)

    async def test_n_limit_respected(self, sample_repo: Path) -> None:
        reader = _reader(sample_repo)
        commits = await reader.get_git_log(n=1)
        assert len(commits) == 1

    async def test_dates_are_timezone_aware(self, sample_repo: Path) -> None:
        reader = _reader(sample_repo)
        commits = await reader.get_git_log()
        for c in commits:
            assert c.date.tzinfo is not None


# ---------------------------------------------------------------------------
# 7. get_blame
# ---------------------------------------------------------------------------


class TestGetBlame:
    async def test_blame_returns_lines(self, sample_repo: Path) -> None:
        reader = _reader(sample_repo)
        blame = await reader.get_blame("config.py", 1, 5)
        assert len(blame) >= 1

    async def test_blame_line_numbers_sequential(self, sample_repo: Path) -> None:
        reader = _reader(sample_repo)
        blame = await reader.get_blame("config.py", 1, 5)
        line_nums = [b.line_number for b in blame]
        assert line_nums == sorted(line_nums)
        assert all(1 <= n <= 5 for n in line_nums)

    async def test_blame_author_populated(self, sample_repo: Path) -> None:
        reader = _reader(sample_repo)
        blame = await reader.get_blame("config.py", 1, 3)
        for line in blame:
            assert line.author  # should not be empty
            assert line.sha     # short sha
            assert line.date.tzinfo is not None

    async def test_blame_content_matches_file(self, sample_repo: Path) -> None:
        reader = _reader(sample_repo)
        blame = await reader.get_blame("config.py", 1, 1)
        file_first_line = (sample_repo / "config.py").read_text().splitlines()[0]
        assert blame[0].content == file_first_line


# ---------------------------------------------------------------------------
# 8. CodeSearchEngine.find_error_source
# ---------------------------------------------------------------------------


class TestFindErrorSource:
    async def test_finds_zero_division_source(self, sample_repo: Path) -> None:
        reader = _reader(sample_repo)
        engine = CodeSearchEngine()

        error_msg = "ZeroDivisionError: division by zero"
        stack = (
            'Traceback (most recent call last):\n'
            f'  File "{sample_repo}/api/app.py", line 32, in calculate_stats\n'
            '    mean = total / len(numbers)\n'
            'ZeroDivisionError: division by zero'
        )
        refs = await engine.find_error_source(error_msg, stack, reader)

        assert len(refs) >= 1
        top = refs[0]
        assert "app.py" in top.file_path
        assert top.relevance_score > 0.5

    async def test_finds_attribute_error_source(self, sample_repo: Path) -> None:
        reader = _reader(sample_repo)
        engine = CodeSearchEngine()

        error_msg = "AttributeError: 'dict' object has no attribute 'user_id'"
        stack = (
            'Traceback (most recent call last):\n'
            f'  File "{sample_repo}/api/app.py", line 52, in process_order\n'
            '    user_id = body.user_id\n'
            "AttributeError: 'dict' object has no attribute 'user_id'"
        )
        refs = await engine.find_error_source(error_msg, stack, reader)

        assert len(refs) >= 1
        assert any("app.py" in r.file_path for r in refs)

    async def test_finds_key_error_source(self, sample_repo: Path) -> None:
        reader = _reader(sample_repo)
        engine = CodeSearchEngine()

        error_msg = "KeyError: 'max_requests_per_user'"
        stack = (
            'Traceback (most recent call last):\n'
            f'  File "{sample_repo}/api/handlers.py", line 25, in handle_user_request\n'
            '    limit = get_config_value("max_requests_per_user")\n'
            f'  File "{sample_repo}/config.py", line 18, in get_config_value\n'
            '    return _CONFIG[key]\n'
            "KeyError: 'max_requests_per_user'"
        )
        refs = await engine.find_error_source(error_msg, stack, reader)

        assert len(refs) >= 1
        # Should find config.py or handlers.py — both are in the traceback
        found_files = {r.file_path for r in refs}
        assert any("config" in f or "handlers" in f for f in found_files)

    async def test_returns_at_most_five_refs(self, sample_repo: Path) -> None:
        reader = _reader(sample_repo)
        engine = CodeSearchEngine()
        refs = await engine.find_error_source("ZeroDivisionError", None, reader)
        assert len(refs) <= 5

    async def test_empty_error_message_returns_empty(self, sample_repo: Path) -> None:
        reader = _reader(sample_repo)
        engine = CodeSearchEngine()
        refs = await engine.find_error_source("", None, reader)
        assert refs == []

    async def test_refs_sorted_by_score_descending(self, sample_repo: Path) -> None:
        reader = _reader(sample_repo)
        engine = CodeSearchEngine()
        refs = await engine.find_error_source(
            "ZeroDivisionError: division by zero", None, reader
        )
        scores = [r.relevance_score for r in refs]
        assert scores == sorted(scores, reverse=True)

    async def test_snippet_populated(self, sample_repo: Path) -> None:
        reader = _reader(sample_repo)
        engine = CodeSearchEngine()
        refs = await engine.find_error_source(
            "ZeroDivisionError: division by zero", None, reader
        )
        for ref in refs:
            assert isinstance(ref.snippet, str)

    async def test_regex_special_chars_in_error_safe(self, sample_repo: Path) -> None:
        """Error messages with regex metacharacters must not raise."""
        reader = _reader(sample_repo)
        engine = CodeSearchEngine()
        for err in [
            "TypeError: unsupported operand type(s) for +: 'int' and 'str'",
            "ValueError: invalid literal for int() with base 10: '2.5'",
            "re.error: nothing to repeat at position 0",
            "KeyError: [1, 2, 3]",
        ]:
            refs = await engine.find_error_source(err, None, reader)
            assert isinstance(refs, list)


# ---------------------------------------------------------------------------
# 9. CodeSearchEngine._extract_terms — unit tests
# ---------------------------------------------------------------------------


class TestExtractTerms:
    def test_extracts_exception_type(self) -> None:
        terms = CodeSearchEngine._extract_terms("ZeroDivisionError: division by zero", None)
        assert "ZeroDivisionError" in terms

    def test_extracts_function_from_traceback(self) -> None:
        stack = "  File \"app.py\", line 10, in calculate_stats\n    x = a / b"
        terms = CodeSearchEngine._extract_terms("ZeroDivisionError", stack)
        assert "calculate_stats" in terms

    def test_extracts_file_stem_from_traceback(self) -> None:
        stack = "  File \"/repo/api/app.py\", line 10, in some_func\n    x = 1"
        terms = CodeSearchEngine._extract_terms("Error", stack)
        assert "app" in terms

    def test_extracts_camelcase_class_names(self) -> None:
        terms = CodeSearchEngine._extract_terms(
            "AttributeError: 'UserManager' object has no attribute 'name'", None
        )
        assert "UserManager" in terms or "AttributeError" in terms

    def test_no_duplicate_terms(self) -> None:
        stack = (
            "  File \"app.py\", line 1, in calculate_stats\n"
            "  File \"app.py\", line 2, in calculate_stats\n"
        )
        terms = CodeSearchEngine._extract_terms("ZeroDivisionError", stack)
        assert len(terms) == len(set(terms))

    def test_empty_inputs_returns_empty(self) -> None:
        terms = CodeSearchEngine._extract_terms("", None)
        assert terms == []

    def test_module_not_in_terms(self) -> None:
        stack = '  File "app.py", line 1, in <module>\n    import foo'
        terms = CodeSearchEngine._extract_terms("ImportError", stack)
        assert "module" not in terms


# ---------------------------------------------------------------------------
# 10. CodeSearchEngine.build_explain_prompt — unit tests
# ---------------------------------------------------------------------------


class TestBuildExplainPrompt:
    def test_prompt_contains_file_path(self) -> None:
        prompt = CodeSearchEngine.build_explain_prompt(
            file_path="api/app.py",
            line_start=30,
            line_end=35,
            snippet="mean = total / len(numbers)",
            error_context="ZeroDivisionError: division by zero",
        )
        assert "api/app.py" in prompt

    def test_prompt_contains_line_range(self) -> None:
        prompt = CodeSearchEngine.build_explain_prompt(
            file_path="app.py",
            line_start=10,
            line_end=20,
            snippet="x = a / b",
            error_context="ZeroDivisionError",
        )
        assert "10" in prompt
        assert "20" in prompt

    def test_prompt_contains_snippet(self) -> None:
        snippet = "mean = total / len(numbers)  # BUG"
        prompt = CodeSearchEngine.build_explain_prompt(
            file_path="app.py",
            line_start=1,
            line_end=1,
            snippet=snippet,
            error_context="ZeroDivisionError",
        )
        assert snippet in prompt

    def test_prompt_contains_error_context(self) -> None:
        error = "ZeroDivisionError: division by zero in calculate_stats"
        prompt = CodeSearchEngine.build_explain_prompt(
            file_path="app.py",
            line_start=1,
            line_end=5,
            snippet="x = a / b",
            error_context=error,
        )
        assert error in prompt

    def test_prompt_has_explanation_instructions(self) -> None:
        prompt = CodeSearchEngine.build_explain_prompt(
            file_path="f.py", line_start=1, line_end=2,
            snippet="pass", error_context="Error",
        )
        # Should ask the model to explain
        assert "explain" in prompt.lower() or "Explain" in prompt

    def test_prompt_mentions_codellama_task(self) -> None:
        prompt = CodeSearchEngine.build_explain_prompt(
            file_path="f.py", line_start=1, line_end=2,
            snippet="pass", error_context="Error",
        )
        # Prompt should address code review / bug analysis
        assert "bug" in prompt.lower() or "error" in prompt.lower()

    def test_prompt_is_string(self) -> None:
        prompt = CodeSearchEngine.build_explain_prompt(
            file_path="f.py", line_start=1, line_end=1,
            snippet="x=1", error_context="err",
        )
        assert isinstance(prompt, str)
        assert len(prompt) > 50


# ---------------------------------------------------------------------------
# 11. Utility helpers
# ---------------------------------------------------------------------------


class TestHelpers:
    def test_detect_language_python(self) -> None:
        assert _detect_language("app.py") == "python"
        assert _detect_language("module.ts") == "typescript"
        assert _detect_language("README.md") == "markdown"
        assert _detect_language("unknown.xyz") == ""

    def test_line_num_from_numbered(self) -> None:
        assert _line_num_from_numbered("     7: some code") == 7
        assert _line_num_from_numbered("  100: x = 1") == 100
        assert _line_num_from_numbered("not a numbered line") == -1

    def test_line_num_from_numbered_edge_cases(self) -> None:
        assert _line_num_from_numbered("") == -1
        assert _line_num_from_numbered("   1: ") == 1


# ---------------------------------------------------------------------------
# Tree traversal helpers (used by multiple test classes)
# ---------------------------------------------------------------------------


def _collect_paths(nodes: list, prefix: str = "") -> list[str]:
    """Recursively collect all file paths from a FileNode list."""
    paths: list[str] = []
    for node in nodes:
        if node.is_dir:
            paths.extend(_collect_paths(node.children, node.path))
        else:
            paths.append(node.path)
    return paths


def _collect_nodes(nodes: list) -> list:
    """Recursively collect all FileNode objects."""
    result = list(nodes)
    for node in nodes:
        if node.is_dir:
            result.extend(_collect_nodes(node.children))
    return result
