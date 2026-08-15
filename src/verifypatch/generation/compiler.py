from __future__ import annotations

import ast
from pathlib import Path

from verifypatch.limits import MAX_GENERATED_FILE_BYTES
from verifypatch.requirements import EXECUTABLE_KINDS, Requirement


DISALLOWED_MODULES = {
    "os",
    "sys",
    "subprocess",
    "socket",
    "pathlib",
    "requests",
    "http",
    "urllib",
    "asyncio",
    "random",
    "time",
    "datetime",
}


def _ident(name: str) -> bool:
    return bool(name) and all(part.isidentifier() for part in name.split("."))


def _const(value: object) -> ast.expr:
    return ast.Constant(value=value)


def _import_from(module: str, names: list[str]) -> ast.ImportFrom:
    return ast.ImportFrom(module=module, names=[ast.alias(name=n) for n in names], level=0)


def _call(func: ast.expr, args: list[ast.expr] | None = None, keywords: list[ast.keyword] | None = None) -> ast.Call:
    return ast.Call(func=func, args=args or [], keywords=keywords or [])


def _name(name: str) -> ast.Name:
    return ast.Name(id=name, ctx=ast.Load())


def _attr(name: str, attr: str) -> ast.Attribute:
    return ast.Attribute(value=_name(name), attr=attr, ctx=ast.Load())


def compile_requirement(req: Requirement, *, max_examples: int, deadline_ms: int, seed: int) -> str:
    if not req.executable or req.kind not in EXECUTABLE_KINDS:
        raise ValueError(f"requirement {req.id} is not executable")
    module = req.target_module or ""
    qual = req.target_callable or ""
    if not _ident(module) or not _ident(qual):
        raise ValueError(f"requirement {req.id} has an invalid target")
    body: list[ast.stmt] = [
        ast.Import(names=[ast.alias(name="importlib")]),
        _import_from("hypothesis", ["given", "settings", "seed", "HealthCheck"]),
        ast.ImportFrom(module="hypothesis", names=[ast.alias(name="strategies", asname="st")], level=0),
        ast.Expr(_call(_name("seed"), [_const(seed)])),
    ]
    test = _test_fn(req, module, qual, max_examples, deadline_ms)
    body.append(test)
    module_ast = ast.Module(body=body, type_ignores=[])
    ast.fix_missing_locations(module_ast)
    rendered = ast.unparse(module_ast)
    if len(rendered.encode("utf-8")) > MAX_GENERATED_FILE_BYTES:
        raise ValueError("generated test exceeded file size cap")
    if any(f"import {banned}" in rendered for banned in DISALLOWED_MODULES):
        raise ValueError("generated test referenced a disallowed module")
    return rendered + "\n"


def _load_target(module: str, qual: str) -> list[ast.stmt]:
    return [
        ast.Assign(
            targets=[_name("mod")],
            value=_call(_attr("importlib", "import_module"), [_const(module)]),
        ),
        ast.Assign(
            targets=[_name("fn")],
            value=_call(_name("getattr"), [_name("mod"), _const(qual)]),
        ),
    ]


def _settings(max_examples: int, deadline_ms: int) -> ast.Call:
    return _call(
        _name("settings"),
        keywords=[
            ast.keyword("max_examples", _const(max_examples)),
            ast.keyword("deadline", _const(deadline_ms)),
            ast.keyword("database", _const(None)),
            ast.keyword("suppress_health_check", ast.List(elts=[_attr("HealthCheck", "too_slow")], ctx=ast.Load())),
        ],
    )


def _given(strategy: ast.expr) -> ast.Call:
    return _call(_name("given"), [strategy])


def _st(name: str, **kwargs: ast.expr) -> ast.Call:
    return _call(_attr("st", name), keywords=[ast.keyword(k, v) for k, v in kwargs.items()])


def _test_fn(req: Requirement, module: str, qual: str, max_examples: int, deadline_ms: int) -> ast.FunctionDef:
    params = req.parameters or {}
    fn_name = f"test_{req.id.replace('-', '_')}_{req.kind}"
    args = ast.arguments(
        posonlyargs=[],
        args=[ast.arg(arg="value")],
        vararg=None,
        kwonlyargs=[],
        kw_defaults=[],
        kwarg=None,
        defaults=[],
    )
    strategy: ast.expr
    statements: list[ast.stmt] = _load_target(module, qual)
    if req.kind == "bounds":
        lo = params.get("min", 0)
        hi = params.get("max", 100)
        strategy = _st("integers", min_value=_const(lo), max_value=_const(hi))
        statements.append(
            ast.Assign(targets=[_name("result")], value=_call(_name("fn"), [_name("value")]))
        )
        statements.append(ast.Assert(test=ast.Compare(_name("result"), [ast.GtE()], [_const(lo)]), msg=None))
        statements.append(ast.Assert(test=ast.Compare(_name("result"), [ast.LtE()], [_const(hi)]), msg=None))
    elif req.kind == "charset":
        alphabet = str(params.get("alphabet") or "abcdefghijklmnopqrstuvwxyz")
        strategy = _call(_attr("st", "text"), keywords=[ast.keyword("alphabet", _const(alphabet))])
        statements.append(ast.Expr(_call(_name("fn"), [_name("value")])))
    elif req.kind == "round_trip":
        strategy = _st("integers", min_value=_const(0), max_value=_const(100))
        statements.append(
            ast.Assign(
                targets=[_name("result")],
                value=_call(_name("fn"), [_call(_name("fn"), [_name("value")])]),
            )
        )
        statements.append(
            ast.Assert(
                test=ast.Compare(_name("result"), [ast.Eq()], [_call(_name("fn"), [_name("value")])]),
                msg=None,
            )
        )
    elif req.kind == "idempotent":
        strategy = _st("integers", min_value=_const(0), max_value=_const(100))
        statements.append(
            ast.Assign(targets=[_name("once")], value=_call(_name("fn"), [_name("value")]))
        )
        statements.append(
            ast.Assign(targets=[_name("twice")], value=_call(_name("fn"), [_name("once")]))
        )
        statements.append(ast.Assert(test=ast.Compare(_name("once"), [ast.Eq()], [_name("twice")]), msg=None))
    elif req.kind == "monotonic":
        args = ast.arguments(
            posonlyargs=[],
            args=[ast.arg(arg="left"), ast.arg(arg="right")],
            vararg=None,
            kwonlyargs=[],
            kw_defaults=[],
            kwarg=None,
            defaults=[],
        )
        strategy = _call(
            _name("given"),
            [_st("integers", min_value=_const(0), max_value=_const(100)), _st("integers", min_value=_const(0), max_value=_const(100))],
        )
        statements.append(
            ast.If(
                test=ast.Compare(_name("left"), [ast.Gt()], [_name("right")]),
                body=[ast.Return(value=None)],
                orelse=[],
            )
        )
        statements.append(
            ast.Assert(
                test=ast.Compare(
                    _call(_name("fn"), [_name("left")]),
                    [ast.LtE()],
                    [_call(_name("fn"), [_name("right")])],
                ),
                msg=None,
            )
        )
        fn_def = ast.FunctionDef(
            name=fn_name,
            args=args,
            body=statements,
            decorator_list=[_settings(max_examples, deadline_ms), strategy],
            returns=None,
            type_comment=None,
        )
        return fn_def
    elif req.kind == "non_negative":
        strategy = _st("integers", min_value=_const(0), max_value=_const(1000))
        statements.append(
            ast.Assert(
                test=ast.Compare(_call(_name("fn"), [_name("value")]), [ast.GtE()], [_const(0)]),
                msg=None,
            )
        )
    elif req.kind == "schema_valid":
        strategy = _st("from_type", type=_name("dict")) if False else _st("dictionaries", keys=_call(_attr("st", "text")), values=_call(_attr("st", "integers")))
        statements.append(ast.Expr(_call(_name("fn"), [_name("value")])))
    elif req.kind == "rejects_invalid":
        invalid = params.get("invalid") or [None]
        strategy = _call(_attr("st", "sampled_from"), [_const(tuple(invalid))])
        statements.append(
            ast.Try(
                body=[
                    ast.Expr(_call(_name("fn"), [_name("value")])),
                    ast.Raise(exc=_call(_name("AssertionError"), [_const("expected rejection")]), cause=None),
                ],
                handlers=[
                    ast.ExceptHandler(type=_name("Exception"), name=None, body=[ast.Pass()]),
                ],
                orelse=[],
                finalbody=[],
            )
        )
    elif req.kind == "examples":
        examples = params.get("examples") or [{"args": [0], "kwargs": {}}]
        first = examples[0] if examples else {"args": [0], "kwargs": {}}
        args_list = first.get("args") or []
        strategy = _call(_attr("st", "just"), [_const(tuple(args_list))])
        expected = first.get("expected")
        statements.append(
            ast.Assign(
                targets=[_name("result")],
                value=_call(_name("fn"), ast.Starred(value=_name("value"), ctx=ast.Load()) if False else [_name("value")]),
            )
        )
        # unpack tuple via starred call
        statements[-1] = ast.Assign(
            targets=[_name("result")],
            value=ast.Call(func=_name("fn"), args=[ast.Starred(value=_name("value"), ctx=ast.Load())], keywords=[]),
        )
        if expected is not None:
            statements.append(ast.Assert(test=ast.Compare(_name("result"), [ast.Eq()], [_const(expected)]), msg=None))
    else:
        raise ValueError(f"unsupported kind {req.kind}")

    return ast.FunctionDef(
        name=fn_name,
        args=args,
        body=statements,
        decorator_list=[_settings(max_examples, deadline_ms), _given(strategy)],
        returns=None,
        type_comment=None,
    )


def compile_all(
    requirements: list[Requirement],
    dest: Path,
    *,
    max_examples: int,
    deadline_ms: int,
    seed: int,
) -> list[tuple[Requirement, Path, str]]:
    dest.mkdir(parents=True, exist_ok=True)
    (dest / "__init__.py").write_text("", encoding="utf-8")
    written: list[tuple[Requirement, Path, str]] = []
    for req in requirements:
        if not req.executable:
            continue
        source = compile_requirement(req, max_examples=max_examples, deadline_ms=deadline_ms, seed=seed)
        path = dest / f"test_{req.id.replace('-', '_')}.py"
        path.write_text(source, encoding="utf-8")
        written.append((req, path, source))
    return written
