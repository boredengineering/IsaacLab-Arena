#!/usr/bin/env python3
# Copyright (c) 2026, The Isaac Lab Arena Project Developers.
# SPDX-License-Identifier: Apache-2.0
"""Durable CPU/offline verification entry. No install, live workflow or credential access.

From the repository root:
  python3 scripts/run-functional-checks.py security-units --node-units
  python3 scripts/run-functional-checks.py api
  python3 scripts/run-functional-checks.py backend
  python3 scripts/run-functional-checks.py typecheck --allow-frontend-verification
  python3 scripts/run-functional-checks.py build --allow-frontend-verification

Typecheck/build execute ordinary npm scripts only inside an owned offline sandbox.
If tool approval denies either command, stop that verification; do not rephrase it.
"""
import argparse
import sys
from pathlib import Path


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument('mode', choices=('security-units', 'api', 'backend', 'typecheck', 'build'))
    parser.add_argument('--node-units', action='store_true')
    parser.add_argument('--browser', action='store_true', help='API: production build and real isolated Chromium')
    parser.add_argument('--layout', choices=('legacy', 'v7'), default='legacy')
    parser.add_argument('--profile', choices=('readonly', 'authoring-v1'), default='readonly')
    parser.add_argument('--runtime-image', help='API/backend: immutable test image ID')
    parser.add_argument('--provision-manifest', help='API/backend: matching verified provisioning manifest')
    parser.add_argument('--frontend-dependency-container', help='Frontend/browser only: exact 64-hex stopped container ID; trusted mutable dependencies')
    parser.add_argument('--allow-frontend-verification', action='store_true')
    parser.add_argument('tests', nargs='*', help='Backend only: exact approved test file paths, never pytest flags')
    options = parser.parse_args(argv)
    if (options.browser or options.layout != 'legacy' or options.profile != 'readonly') and options.mode != 'api':
        parser.error('Browser/layout/profile forwarding requires api mode')
    if options.frontend_dependency_container is not None and not (options.mode in ('typecheck', 'build') or (options.mode == 'api' and options.browser)):
        parser.error('--frontend-dependency-container requires typecheck/build or api --browser')
    if options.node_units and options.mode != 'security-units':
        parser.error('--node-units requires security-units')
    if options.allow_frontend_verification and options.mode not in ('typecheck', 'build'):
        parser.error('Frontend gate is only for typecheck/build')
    if (options.runtime_image is not None or options.provision_manifest is not None) and options.mode not in ('api', 'backend'):
        parser.error('Provisioned image selection requires api or backend mode')
    if (options.runtime_image is None) != (options.provision_manifest is None):
        parser.error('--runtime-image and --provision-manifest must be paired')
    if options.tests and options.mode != 'backend':
        parser.error('Only backend accepts exact test paths')
    root = Path(__file__).resolve().parents[1]
    here = root / 'web/arena-workbench/tests/e2e/functional-v7'
    sys.path.insert(0, str(here))
    if options.mode == 'api':
        import run
        args = []
        if options.browser:
            args += ['--browser']
        if options.layout != 'legacy':
            args += ['--layout', options.layout]
        if options.profile != 'readonly':
            args += ['--profile', options.profile]
        for name in ('runtime_image', 'provision_manifest', 'frontend_dependency_container'):
            value = getattr(options, name)
            if value is not None:
                args += ['--' + name.replace('_', '-'), value]
        return run.main(args)
    if options.mode == 'security-units':
        import self_test
        sys.argv = [str(here / 'self_test.py'), *(['--node-units'] if options.node_units else [])]
        return self_test.main()
    if options.mode == 'backend':
        import backend_checks
        return backend_checks.main(options.tests, runtime_image=options.runtime_image,
                                   provision_manifest=options.provision_manifest)
    import frontend_checks
    return frontend_checks.main(options.mode, options.allow_frontend_verification,
                                frontend_dependency_container=options.frontend_dependency_container)


if __name__ == '__main__':
    raise SystemExit(main())
