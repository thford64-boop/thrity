#!/usr/bin/env python3
"""
Thrity Extension DSL - interpreter
--------------------------------------
Executes the statement lists produced by dsl_parser for an `on
<event> { ... }` or `action <name> { ... }` block.

Why this is safe by construction (not just "trusted"):
  - There is no `eval`, `exec`, `compile`, `import`, or any other
    path from extension text to arbitrary Python execution anywhere
    in this file. The interpreter only ever does one of: evaluate a
    literal, look up a field on `event`/`settings`/local variables,
    call a name that is EITHER a user-defined `action` in the same
    extension OR one of the fixed builtin names implemented in
    api.py - nothing else is reachable, no matter what the DSL text
    says.
  - Every builtin in api.py checks the extension's declared
    `permissions` before doing anything (see ExtensionAPI._require).
    An extension that didn't declare `network` cannot call
    `http_get`, full stop - the interpreter has no way to bypass
    that check since it never touches ExtensionAPI's internals
    directly.
  - There is no file, socket, subprocess, or `os`/`sys` access of
    any kind available to extension code. The only "network" or
    "storage" extension code can ever reach is what api.py exposes,
    and both of those are themselves restricted (see api.py).
"""


class ExtensionRuntimeError(Exception):
    pass


class ControlSignal(Exception):
    """Not currently used for loops (the DSL has none), kept as a
    hook point for future control-flow features without needing a
    redesign."""


def eval_expr(expr, env, api, manifest):
    kind = expr["kind"]
    if kind == "str":
        return expr["value"]
    if kind == "num":
        return expr["value"]
    if kind == "bool":
        return expr["value"]
    if kind == "var":
        if expr["name"] in env["locals"]:
            return env["locals"][expr["name"]]
        raise ExtensionRuntimeError(f"undefined variable: {expr['name']}")
    if kind == "field":
        base = expr["base"]
        if base == "event":
            return env["event"].get(expr["name"])
        if base == "settings":
            return manifest.settings.get(expr["name"])
        raise ExtensionRuntimeError(f"unknown value: {base}.{expr['name']}")
    if kind == "binop":
        left = eval_expr(expr["left"], env, api, manifest)
        right = eval_expr(expr["right"], env, api, manifest)
        if expr["op"] == "+":
            return f"{left}{right}" if isinstance(left, str) or isinstance(right, str) else left + right
        if expr["op"] == "==":
            return left == right
        if expr["op"] == "!=":
            return left != right
        raise ExtensionRuntimeError(f"unknown operator: {expr['op']}")
    if kind == "call":
        return call_function(expr["name"], expr["args"], env, api, manifest)
    raise ExtensionRuntimeError(f"cannot evaluate expression kind: {kind}")


def call_function(name, arg_exprs, env, api, manifest):
    args = [eval_expr(a, env, api, manifest) for a in arg_exprs]

    # user-defined actions take priority so an extension can name an
    # action the same as a builtin if it really wants to shadow it
    if name in manifest.actions:
        if env["depth"] > 20:
            raise ExtensionRuntimeError("action call depth exceeded (possible recursive loop)")
        exec_statements(manifest.actions[name], {**env, "depth": env["depth"] + 1}, api, manifest)
        return None

    builtin = getattr(api, name, None)
    if builtin is None or name.startswith("_"):
        raise ExtensionRuntimeError(f"unknown function: {name}")
    return builtin(*args)


def exec_statements(stmts, env, api, manifest):
    for stmt in stmts:
        exec_statement(stmt, env, api, manifest)


def exec_statement(stmt, env, api, manifest):
    kind = stmt["kind"]
    if kind == "expr_stmt":
        eval_expr(stmt["expr"], env, api, manifest)
    elif kind == "let":
        env["locals"][stmt["name"]] = eval_expr(stmt["expr"], env, api, manifest)
    elif kind == "if":
        cond = eval_expr(stmt["cond"], env, api, manifest)
        branch = stmt["then"] if cond else stmt["else"]
        exec_statements(branch, env, api, manifest)
    else:
        raise ExtensionRuntimeError(f"unknown statement kind: {kind}")


def run(stmts, manifest, api, event=None):
    """Entry point used by the loader/event bus. `event` is a plain
    dict of primitives (strings/numbers/bools) describing what
    happened - never a live object - so extension code can't reach
    back into the browser through it."""
    env = {"event": event or {}, "locals": {}, "depth": 0}
    try:
        exec_statements(stmts, env, api, manifest)
    except ExtensionRuntimeError as e:
        api.log(f"[error] {e}")
    except Exception as e:
        # Covers PermissionError_ from api.py (undeclared permission
        # used), FileNotFoundError from run_page_script, etc. - any
        # single extension misbehaving must never propagate out into
        # the browser's event dispatch loop and affect other
        # extensions or the page itself.
        api.log(f"[error] {type(e).__name__}: {e}")
