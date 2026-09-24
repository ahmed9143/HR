"""Route-collision detector — proves which layer actually wins at runtime.

The application is assembled by thirteen modules that each wrap H.do_GET /
H.do_POST and replace globals. Whether a request reaches a given layer's
authorization check depends entirely on import order, and nothing in the
codebase made that visible.

This tool walks the wrapper chain in the real, fully-imported process and
reports, per path, which layer claims it and which layers are shadowed. A
shadowed layer that performs an authorization check is flagged, because its
check is dead code at runtime.

KNOWN LIMITATION: a layer's do_POST handles many routes in one function, so the
permissions reported for a route are every permission that function mentions,
not only the ones guarding that route. Entries can therefore be flagged when the
layers actually agree. Treat this report as a place to look, and confirm real
behaviour with tests/security/TEST_QR_AUTHORIZATION.py, which drives each role
over HTTP.

Run:  python tests/security/TEST_ROUTE_COLLISIONS.py [--report]
"""
import os, re, sys, json, tempfile, pathlib, inspect

ROOT = pathlib.Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT))
os.chdir(ROOT)
os.environ.setdefault('HR_DATA_DIR', tempfile.mkdtemp(prefix='route_audit_'))
os.environ.setdefault('HR_BOOTSTRAP_PASSWORD', 'TestAdmin@12345')
os.environ.setdefault('HR_NO_BROWSER', '1')

# Paths whose winner materially affects security or the user-visible contract.
CRITICAL = [
    '/id-cards', '/login', '/logout', '/password',
    '/qr/generate', '/qr/regenerate', '/qr/generate-all', '/qr/bulk', '/qr/scan',
    '/employees', '/employee/operations', '/employee/operations/qr',
    '/employee/operations/export', '/employee/operations/provision',
    '/backup', '/backup/restore', '/backups', '/system/backup', '/roles', '/settings',
    '/zkteco/devices', '/zkteco/sync', '/health', '/health/deep',
]

AUTH_MARKERS = ('is_admin', 'can(', 'forbid', 'require()', 'must_change_password')


def wrapper_chain(func):
    """Walk a wrapped handler back through every closure layer."""
    chain = []
    seen = set()
    stack = [func]
    while stack:
        fn = stack.pop(0)
        if fn is None or id(fn) in seen:
            continue
        seen.add(id(fn))
        try:
            module = inspect.getmodule(fn)
            src_file = inspect.getsourcefile(fn) or '?'
            line = fn.__code__.co_firstlineno
            chain.append({
                'module': pathlib.Path(src_file).stem,
                'name': fn.__name__,
                'line': line,
                'func': fn,
            })
        except Exception:
            continue
        # Follow the layer convention: each wrapper captures the previous
        # handler in a free variable named old_get / old_post / old_post2 / ...
        # Matching on the *function* name is not enough — layers define post2,
        # get2 etc., and an earlier version of this tool silently stopped at
        # depth 0 for POST because of exactly that.
        code = getattr(fn, '__code__', None)
        closure = getattr(fn, '__closure__', None) or ()
        names = getattr(code, 'co_freevars', ()) if code else ()
        for varname, cell in zip(names, closure):
            try:
                val = cell.cell_contents
            except ValueError:
                continue
            if callable(val) and (varname.startswith('old_') or
                                  re.match(r'^(get|post|do_GET|do_POST)\d*$', getattr(val, '__name__', ''))):
                stack.append(val)
    return chain


def claims(entry, path):
    """Does this layer's source mention this exact path?"""
    try:
        src = inspect.getsource(entry['func'])
    except Exception:
        return False, ''
    if f"'{path}'" in src or f'"{path}"' in src:
        # Compare the PERMISSIONS actually required, not the category of guard
        # used. An earlier version compared marker names (can/forbid/is_admin),
        # so two layers demanding the very same permission were reported as a
        # divergence purely because one of them also called forbid(). That noise
        # made the report unusable for deciding whether a real split existed.
        perms = set(re.findall(r"can\(u,\s*['\"]([^'\"]+)['\"]\)", src))
        if re.search(r'\bis_admin\(', src):
            perms.add('role:admin')
        return True, ','.join(sorted(perms)) if perms else ''
    return False, ''


def main():
    import server  # triggers the full import/patch chain

    H = server.H
    results = {}
    for verb, handler in (('GET', H.do_GET), ('POST', H.do_POST)):
        chain = wrapper_chain(handler)
        for path in CRITICAL:
            claimants = []
            for depth, entry in enumerate(chain):
                hit, markers = claims(entry, path)
                if hit:
                    claimants.append({'depth': depth, 'module': entry['module'],
                                      'line': entry['line'], 'auth': markers})
            if claimants:
                results.setdefault(path, {})[verb] = claimants

    print('=' * 78)
    print('RUNTIME ROUTE OWNERSHIP  (depth 0 = outermost = runs first = WINNER)')
    print('=' * 78)
    collisions = []
    for path in CRITICAL:
        if path not in results:
            continue
        for verb, claimants in sorted(results[path].items()):
            winner = claimants[0]
            shadowed = claimants[1:]
            print(f'\n{verb:5} {path}')
            print(f'      WINNER   {winner["module"]}:{winner["line"]}'
                  + (f'   auth=[{winner["auth"]}]' if winner['auth'] else '   auth=[none]'))
            for s in shadowed:
                # Only a genuine divergence counts: the shadowed layer demands a
                # permission the winner does not.
                shadow_perms = set(filter(None, s['auth'].split(',')))
                winner_perms = set(filter(None, winner['auth'].split(',')))
                dead_check = bool(shadow_perms - winner_perms)
                flag = '  <-- SHADOWED AUTH CHECK' if dead_check else ''
                print(f'      shadowed {s["module"]}:{s["line"]}'
                      + (f'   auth=[{s["auth"]}]' if s['auth'] else '   auth=[none]') + flag)
                if dead_check:
                    collisions.append({
                        'path': path, 'verb': verb,
                        'winner': f'{winner["module"]}:{winner["line"]}',
                        'winner_auth': winner['auth'],
                        'shadowed': f'{s["module"]}:{s["line"]}',
                        'shadowed_auth': s['auth'],
                    })

    print('\n' + '=' * 78)
    if collisions:
        print(f'{len(collisions)} SHADOWED AUTHORIZATION CHECK(S) — these never execute:')
        for c in collisions:
            print(f"  {c['verb']} {c['path']}")
            print(f"     enforced : {c['winner']}  [{c['winner_auth'] or 'none'}]")
            print(f"     dead code: {c['shadowed']}  [{c['shadowed_auth']}]")
    else:
        print('No shadowed authorization checks detected on critical paths.')
    print('=' * 78)

    out = ROOT / 'docs' / 'ROUTE_OWNERSHIP.json'
    out.parent.mkdir(exist_ok=True)
    out.write_text(json.dumps({'routes': results, 'shadowed_auth': collisions},
                              indent=2, default=str), encoding='utf-8')
    print(f'Machine-readable map written to {out.relative_to(ROOT)}')

    # This tool reports; it does not fail the build. Turning a detected
    # collision into a hard failure is a policy decision for CI, made once the
    # currently-known collisions are triaged.
    return 0


if __name__ == '__main__':
    sys.exit(main())
