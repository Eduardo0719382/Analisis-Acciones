"""Update service against real temporary git repositories (no network)."""

from __future__ import annotations

import subprocess
from collections.abc import Sequence
from pathlib import Path

import pytest

from analisis_acciones.models.errors import InternalError, NetworkError, UserError
from analisis_acciones.services.update_service import UpdateService, run_command


@pytest.fixture(autouse=True)
def git_identity(monkeypatch: pytest.MonkeyPatch) -> None:
    for var in ("GIT_AUTHOR_NAME", "GIT_COMMITTER_NAME"):
        monkeypatch.setenv(var, "Test")
    for var in ("GIT_AUTHOR_EMAIL", "GIT_COMMITTER_EMAIL"):
        monkeypatch.setenv(var, "test@example.com")


def git(cwd: Path, *args: str) -> str:
    return subprocess.run(
        ["git", *args], cwd=cwd, check=True, capture_output=True, text=True
    ).stdout.strip()


def commit_file(repo: Path, name: str, content: str, message: str) -> None:
    (repo / name).parent.mkdir(parents=True, exist_ok=True)
    (repo / name).write_text(content, encoding="utf-8")
    git(repo, "add", name)
    git(repo, "commit", "-q", "-m", message)


class Repos:
    def __init__(self, tmp: Path) -> None:
        self.origin = tmp / "origin.git"
        self.dev = tmp / "dev"
        self.install = tmp / "install"
        git(tmp, "init", "-q", "--bare", "-b", "main", str(self.origin))
        git(tmp, "clone", "-q", str(self.origin), str(self.dev))
        git(self.dev, "checkout", "-q", "-b", "main")
        commit_file(self.dev, "pyproject.toml", "v1\n", "Initial")
        commit_file(self.dev, "src/analisis_acciones/app.py", "x = 1\n", "Add app")
        git(self.dev, "push", "-q", "-u", "origin", "main")
        git(tmp, "clone", "-q", str(self.origin), str(self.install))

    @property
    def package_dir(self) -> Path:
        return self.install / "src" / "analisis_acciones"

    def publish(self, name: str, content: str, message: str) -> None:
        commit_file(self.dev, name, content, message)
        git(self.dev, "push", "-q")


class RecordingRunner:
    """Runs git for real; records pip calls and returns a configurable result."""

    def __init__(self, pip_returncode: int = 0) -> None:
        self.pip_calls: list[list[str]] = []
        self.pip_returncode = pip_returncode

    def __call__(self, args: Sequence[str], cwd: Path) -> subprocess.CompletedProcess[str]:
        if "pip" in args:
            self.pip_calls.append(list(args))
            return subprocess.CompletedProcess(list(args), self.pip_returncode, "", "pip error")
        return run_command(args, cwd)


@pytest.fixture
def repos(tmp_path: Path) -> Repos:
    return Repos(tmp_path)


def service(repos: Repos, runner: RecordingRunner | None = None) -> UpdateService:
    return UpdateService(repos.package_dir, runner or RecordingRunner(), "python-test")


def test_up_to_date(repos: Repos) -> None:
    check = service(repos).check()
    assert not check.available
    assert check.behind == 0
    assert check.branch == "main"
    assert check.changes == []


def test_update_available_and_applied(repos: Repos) -> None:
    repos.publish("src/analisis_acciones/app.py", "x = 2\n", "Mejora del gráfico")
    repos.publish("README.md", "hola\n", "Docs")
    runner = RecordingRunner()
    svc = service(repos, runner)

    check = svc.check()
    assert check.available
    assert check.behind == 2
    assert check.changes == ["Docs", "Mejora del gráfico"]

    result = svc.apply()
    assert result.new_commit == check.remote_commit
    assert not result.dependencies_reinstalled
    assert runner.pip_calls == []
    assert (repos.package_dir / "app.py").read_text(encoding="utf-8") == "x = 2\n"
    assert not svc.check().available


def test_dependencies_reinstalled_when_pyproject_changes(repos: Repos) -> None:
    repos.publish("pyproject.toml", "v2\n", "New dependency")
    runner = RecordingRunner()
    svc = service(repos, runner)
    svc.check()
    assert svc.apply().dependencies_reinstalled
    assert runner.pip_calls == [["python-test", "-m", "pip", "install", "-e", str(repos.install)]]


def test_pip_failure_is_reported(repos: Repos) -> None:
    repos.publish("pyproject.toml", "v2\n", "New dependency")
    svc = service(repos, RecordingRunner(pip_returncode=1))
    svc.check()
    with pytest.raises(InternalError) as info:
        svc.apply()
    assert "pip install -e ." in info.value.user_message


def test_local_changes_block_update(repos: Repos) -> None:
    repos.publish("src/analisis_acciones/app.py", "x = 2\n", "Change")
    (repos.package_dir / "app.py").write_text("x = 99\n", encoding="utf-8")
    svc = service(repos)
    svc.check()
    with pytest.raises(UserError, match="local changes"):
        svc.apply()
    assert (repos.package_dir / "app.py").read_text(encoding="utf-8") == "x = 99\n"


def test_untracked_files_do_not_block_update(repos: Repos) -> None:
    repos.publish("README.md", "hola\n", "Docs")
    (repos.install / "notes.txt").write_text("mine", encoding="utf-8")
    svc = service(repos)
    svc.check()
    svc.apply()
    assert (repos.install / "notes.txt").exists()


def test_diverged_branch_is_rejected(repos: Repos) -> None:
    repos.publish("README.md", "remote\n", "Remote change")
    commit_file(repos.install, "local.txt", "x", "Local commit")
    with pytest.raises(UserError) as info:
        service(repos).check()
    assert "cambios propios" in info.value.user_message


def test_not_a_git_checkout(tmp_path: Path) -> None:
    folder = tmp_path / "zip-install" / "src" / "analisis_acciones"
    folder.mkdir(parents=True)
    # Prevent git from discovering a repository in a parent directory.
    svc = UpdateService(folder, lambda a, c: run_command(a, c), "python-test")
    with pytest.MonkeyPatch.context() as mp:
        mp.setenv("GIT_CEILING_DIRECTORIES", str(tmp_path))
        with pytest.raises(UserError) as info:
            svc.check()
    assert "ZIP" in info.value.user_message


def test_git_not_installed(repos: Repos) -> None:
    def missing(args: Sequence[str], cwd: Path) -> subprocess.CompletedProcess[str]:
        raise FileNotFoundError("git")

    with pytest.raises(UserError) as info:
        UpdateService(repos.package_dir, missing).check()
    assert "Git no está instalado" in info.value.user_message


def test_network_failure_on_fetch(repos: Repos) -> None:
    git(repos.install, "remote", "set-url", "origin", str(repos.install.parent / "missing.git"))
    with pytest.raises(NetworkError):
        service(repos).check()


def test_branch_without_upstream(repos: Repos) -> None:
    git(repos.install, "checkout", "-q", "-b", "local-only")
    with pytest.raises(UserError) as info:
        service(repos).check()
    assert "local-only" in info.value.user_message


def test_detached_head(repos: Repos) -> None:
    git(repos.install, "checkout", "-q", "--detach")
    with pytest.raises(UserError, match="detached"):
        service(repos).check()
