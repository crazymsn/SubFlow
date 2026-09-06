"""Reclaim unused SDKs only on disposable GitHub-hosted release runners."""
import os
import shutil
import subprocess
import sys
from pathlib import Path


def main():
    if os.environ.get('GITHUB_ACTIONS') != 'true' or os.environ.get('RUNNER_ENVIRONMENT') != 'github-hosted':
        raise SystemExit('This script only runs on disposable GitHub-hosted runners.')
    workspace = Path(os.environ['GITHUB_WORKSPACE']).resolve()
    print(f'Workspace free before: {shutil.disk_usage(workspace).free / 2**30:.1f} GiB', flush=True)
    targets = []
    if sys.platform == 'darwin':
        active = Path(subprocess.check_output(['xcode-select', '-p'], text=True).strip()).resolve()
        for candidate in Path('/Applications').glob('Xcode*.app'):
            resolved = candidate.resolve()
            if (resolved.parent == Path('/Applications') and not candidate.is_symlink()
                    and not active.is_relative_to(resolved)):
                targets.append(resolved)
    elif sys.platform == 'linux':
        targets = [Path(p) for p in ('/usr/local/lib/android', '/usr/share/dotnet', '/opt/ghc')]
    elif sys.platform == 'win32':
        targets = [Path(p) for p in ('C:/Android', 'C:/Program Files/Android', 'C:/hostedtoolcache/CodeQL')]
    for target in targets:
        resolved = target.resolve()
        # Never follow SDK links outside the named directory or touch the checkout.
        if resolved != target.absolute() or target.is_symlink() or not target.is_dir():
            continue
        if workspace == resolved or workspace.is_relative_to(resolved) or resolved.is_relative_to(workspace):
            raise RuntimeError(f'Refusing to remove a workspace path: {resolved}')
        print(f'Removing unused hosted-runner SDK: {resolved}', flush=True)
        if sys.platform == 'win32':
            shutil.rmtree(resolved)
        else:
            subprocess.run(['sudo', 'rm', '-rf', '--', str(resolved)], check=True)
    print(f'Workspace free after: {shutil.disk_usage(workspace).free / 2**30:.1f} GiB', flush=True)


if __name__ == '__main__':
    main()
