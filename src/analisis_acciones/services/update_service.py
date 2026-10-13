"""Self-update for installations that are a git checkout (``git clone`` + ``pip install -e``).

The service only fast-forwards the current branch to its upstream. It never
merges, rebases or discards local changes. When ``pyproject.toml`` changed,
dependencies are reinstalled with the running interpreter's pip.

Commit messages returned by git are treated as plain data for display.
"""

from __future__ import annotations

import logging
import subprocess
import sys
from collections.abc import Callable, Sequence
from dataclasses import dataclass
from pathlib import Path

from analisis_acciones.models.errors import InternalError, NetworkError, UserError

logger = logging.getLogger(__name__)

# (args, cwd) -> completed process. Injected so tests can replace it.
CommandRunner = Callable[[Sequence[str], Path], "subprocess.CompletedProcess[str]"]

_GIT_MISSING = (
    "Git no está instalado o no está en el PATH. "
    "Instálelo desde https://git-scm.com y reinicie el programa."
)

RELEASES_URL = "https://github.com/Eduardo0719382/Analisis-Acciones/releases"
MAX_LISTED_CHANGES = 20
GIT_TIMEOUT_S = 60
PIP_TIMEOUT_S = 900


def run_command(args: Sequence[str], cwd: Path) -> subprocess.CompletedProcess[str]:
    creationflags = getattr(subprocess, "CREATE_NO_WINDOW", 0)  # no console flash on Windows
    timeout = PIP_TIMEOUT_S if "pip" in args else GIT_TIMEOUT_S
    return subprocess.run(
        list(args),
        cwd=cwd,
        capture_output=True,
        text=True,
        encoding="utf-8",
        errors="replace",
        timeout=timeout,
        check=False,
        creationflags=creationflags,
    )


@dataclass(frozen=True)
class UpdateCheck:
    branch: str
    current_commit: str
    remote_commit: str
    behind: int
    changes: list[str]

    @property
    def available(self) -> bool:
        return self.behind > 0


@dataclass(frozen=True)
class UpdateResult:
    old_commit: str
    new_commit: str
    dependencies_reinstalled: bool


class UpdateService:
    def __init__(
        self,
        package_dir: Path | None = None,
        runner: CommandRunner = run_command,
        python_executable: str = sys.executable,
        frozen: bool | None = None,
    ) -> None:
        self._package_dir = package_dir or Path(__file__).resolve().parents[1]
        self._run = runner
        self._python = python_executable
        self._root: Path | None = None
        #: True inside a PyInstaller build (no git checkout to update).
        self._frozen = bool(getattr(sys, "frozen", False)) if frozen is None else frozen

    # Helpers ---------------------------------------------------------------
    def _git(self, *args: str, cwd: Path | None = None) -> str:
        try:
            proc = self._run(["git", *args], cwd or self.repository_root())
        except FileNotFoundError as exc:
            raise UserError("git executable not found", user_message=_GIT_MISSING) from exc
        except subprocess.TimeoutExpired as exc:
            raise NetworkError(f"git {' '.join(args)} timed out") from exc
        if proc.returncode != 0:
            raise _GitFailed(args, proc.returncode, proc.stderr.strip())
        return proc.stdout.strip()

    def repository_root(self) -> Path:
        if self._frozen:
            raise UserError(
                "installed (frozen) build cannot self-update via git",
                user_message=(
                    "Esta es la versión instalada. Para actualizar, descargue e instale la última "
                    f"versión desde {RELEASES_URL} (sus datos se conservan)."
                ),
            )
        if self._root is None:
            try:
                out = self._git("rev-parse", "--show-toplevel", cwd=self._package_dir)
            except _GitFailed as exc:
                raise UserError(
                    f"{self._package_dir} is not inside a git checkout: {exc}",
                    user_message=(
                        "Esta instalación no se hizo con Git (por ejemplo, desde un ZIP), "
                        "así que no puede actualizarse automáticamente. Vuelva a instalar "
                        "con «git clone» siguiendo el README."
                    ),
                ) from exc
            self._root = Path(out)
        return self._root

    def _branch_and_upstream(self) -> tuple[str, str]:
        branch = self._git("rev-parse", "--abbrev-ref", "HEAD")
        if branch == "HEAD":
            raise UserError(
                "detached HEAD",
                user_message="La copia local no está en ninguna rama; no se puede actualizar.",
            )
        try:
            upstream = self._git("rev-parse", "--abbrev-ref", "--symbolic-full-name", "@{u}")
        except _GitFailed as exc:
            raise UserError(
                f"branch {branch} has no upstream: {exc}",
                user_message=f"La rama «{branch}» no está vinculada a una rama remota.",
            ) from exc
        return branch, upstream

    def _ensure_clean(self) -> None:
        dirty = self._git("status", "--porcelain", "--untracked-files=no")
        if dirty:
            raise UserError(
                f"working tree has local changes:\n{dirty}",
                user_message=(
                    "Hay archivos del programa modificados localmente. "
                    "No se actualizará para no perder esos cambios."
                ),
            )

    # Public API ------------------------------------------------------------
    def check(self) -> UpdateCheck:
        """Fetch the upstream branch and report how far behind the local copy is."""
        branch, upstream = self._branch_and_upstream()
        remote_name = upstream.split("/", 1)[0]
        try:
            self._git("fetch", "--quiet", remote_name)
        except _GitFailed as exc:
            raise NetworkError(
                f"git fetch failed: {exc}",
                user_message=("No se pudo contactar con GitHub. Compruebe su conexión a Internet."),
            ) from exc

        current = self._git("rev-parse", "HEAD")
        remote = self._git("rev-parse", "@{u}")
        behind = int(self._git("rev-list", "--count", "HEAD..@{u}") or 0)
        ahead = int(self._git("rev-list", "--count", "@{u}..HEAD") or 0)
        if ahead and behind:
            raise UserError(
                f"local branch diverged from {upstream} (ahead {ahead}, behind {behind})",
                user_message=(
                    "La copia local tiene cambios propios que no están en GitHub; "
                    "no se puede actualizar automáticamente."
                ),
            )
        log = self._git("log", f"--max-count={MAX_LISTED_CHANGES}", "--format=%s", "HEAD..@{u}")
        changes = [line for line in log.splitlines() if line.strip()]
        logger.info("Update check on %s: %d commit(s) behind %s", branch, behind, upstream)
        return UpdateCheck(branch, current, remote, behind, changes)

    def apply(self) -> UpdateResult:
        """Fast-forward to upstream and reinstall dependencies if they changed."""
        self._ensure_clean()
        old = self._git("rev-parse", "HEAD")
        try:
            self._git("merge", "--ff-only", "--quiet", "@{u}")
        except _GitFailed as exc:
            raise UserError(
                f"fast-forward failed: {exc}",
                user_message="No se pudo aplicar la actualización (la copia local ha divergido).",
            ) from exc
        new = self._git("rev-parse", "HEAD")

        changed = self._git("diff", "--name-only", old, new).splitlines()
        reinstalled = False
        if "pyproject.toml" in changed:
            self._reinstall_dependencies()
            reinstalled = True
        logger.info("Updated %s -> %s (deps reinstalled: %s)", old[:8], new[:8], reinstalled)
        return UpdateResult(old, new, reinstalled)

    def _reinstall_dependencies(self) -> None:
        root = self.repository_root()
        try:
            proc = self._run([self._python, "-m", "pip", "install", "-e", str(root)], root)
        except subprocess.TimeoutExpired as exc:
            raise NetworkError("pip install timed out") from exc
        if proc.returncode != 0:
            logger.error("pip install failed:\n%s", proc.stderr)
            raise InternalError(
                f"pip install failed with code {proc.returncode}",
                user_message=(
                    "El código se actualizó, pero no se pudieron instalar las dependencias. "
                    "Cierre el programa y ejecute en la cmd: pip install -e ."
                ),
            )


class _GitFailed(Exception):
    def __init__(self, args: Sequence[str], code: int, stderr: str) -> None:
        super().__init__(f"git {' '.join(args)} exited {code}: {stderr}")
