"""Generate field manifests from trusted consumer code in an isolated process."""

import argparse
import ast
import builtins
import contextlib
import dataclasses
import fnmatch
import importlib
import io
import json
import math
import os
import secrets
import stat
import subprocess
import sys
import tempfile
import traceback
from pathlib import Path

DISCOVERY_TIMEOUT = 30


class UnsafeImportError(RuntimeError, ValueError):
    """Discovery attempted terminal input."""


def _spellings(tree, symbol):
    names = set()
    modules = set()
    for node in ast.walk(tree):
        if isinstance(node, ast.ImportFrom) and node.module == "dataclasses":
            for alias in node.names:
                if alias.name == symbol:
                    names.add(alias.asname or symbol)
                elif alias.name == "*":
                    names.add(symbol)
        elif isinstance(node, ast.Import):
            for alias in node.names:
                if alias.name == "dataclasses":
                    modules.add(alias.asname or "dataclasses")
    return names, modules


def _matches(node, names, modules, symbol):
    return (isinstance(node, ast.Name) and node.id in names) or (
        isinstance(node, ast.Attribute) and node.attr == symbol
        and isinstance(node.value, ast.Name) and node.value.id in modules
    )


def _source_classes(path):
    tree = ast.parse(path.read_bytes(), filename=str(path))
    names, modules = _spellings(tree, "dataclass")
    fields, field_modules = _spellings(tree, "field")
    makers, maker_modules = _spellings(tree, "make_dataclass")
    parents = {child: node for node in ast.walk(tree) for child in ast.iter_child_nodes(node)}
    decorator_calls = set()
    classes, required = set(), set()
    probe = any((isinstance(n, ast.Name) and n.id in ("dataclass", "make_dataclass"))
                or (isinstance(n, ast.Attribute) and n.attr in ("dataclass", "make_dataclass"))
                for n in ast.walk(tree))
    for node in ast.walk(tree):
        if not isinstance(node, ast.ClassDef) or not node.decorator_list:
            continue
        ancestor = parents.get(node)
        nested = False
        while ancestor is not None:
            if isinstance(ancestor, (ast.ClassDef, ast.FunctionDef, ast.AsyncFunctionDef, ast.Lambda)):
                nested = True
            ancestor = parents.get(ancestor)
        known = any(_matches(d.func if isinstance(d, ast.Call) else d, names, modules, "dataclass")
                    for d in node.decorator_list)
        probe = True
        if nested:
            spelling = lambda d: d.func if isinstance(d, ast.Call) else d
            named_dataclass = any((isinstance(spelling(d), ast.Name) and spelling(d).id == "dataclass")
                                 or (isinstance(spelling(d), ast.Attribute) and spelling(d).attr == "dataclass")
                                 for d in node.decorator_list)
            if known or named_dataclass:
                raise ValueError("nested and function-local dataclasses are unsupported: %s:%s" % (path, node.lineno))
            continue
        if node.name in classes:
            raise ValueError("duplicate dataclass identity: %s.%s" % (path, node.name))
        classes.add(node.name)
        if known:
            required.add(node.name)
        for decorator in node.decorator_list:
            target = decorator.func if isinstance(decorator, ast.Call) else decorator
            if isinstance(decorator, ast.Call):
                decorator_calls.add(decorator)
            if isinstance(decorator, ast.Call) and _matches(target, names, modules, "dataclass"):
                decorator_calls.add(decorator)
                if decorator.args or any(k.arg != "frozen" for k in decorator.keywords):
                    raise ValueError("unsupported dataclass arguments: %s:%s; only frozen is supported" % (path, node.lineno))
    for node in ast.walk(tree):
        if not isinstance(node, ast.Call):
            continue
        if classes and _matches(node.func, fields, field_modules, "field"):
            if node.args or any(k.arg not in ("default", "default_factory") for k in node.keywords):
                raise ValueError("unsupported field arguments: %s:%s" % (path, node.lineno))
        named_make = ((isinstance(node.func, ast.Name) and node.func.id == "make_dataclass")
                      or (isinstance(node.func, ast.Attribute) and node.func.attr == "make_dataclass"))
        named_dataclass = ((isinstance(node.func, ast.Name) and node.func.id == "dataclass")
                           or (isinstance(node.func, ast.Attribute) and node.func.attr == "dataclass"))
        if (_matches(node.func, makers, maker_modules, "make_dataclass") or named_make or
            ((_matches(node.func, names, modules, "dataclass") or named_dataclass) and node not in decorator_calls)):
            ancestor = parents.get(node)
            local = False
            while ancestor is not None:
                if isinstance(ancestor, (ast.FunctionDef, ast.AsyncFunctionDef, ast.Lambda)):
                    local = True
                ancestor = parents.get(ancestor)
            if not local:
                raise ValueError("dataclasses must use decorator syntax: %s:%s" % (path, node.lineno))
    return classes, required, probe


def _module_name(source_root, path):
    parts = list(path.relative_to(source_root).with_suffix("").parts)
    if parts[-1] == "__init__":
        parts.pop()
    return ".".join(parts)


def _excluded(source_root, path, patterns):
    relative = path.relative_to(source_root).as_posix()
    return any(relative == pattern.rstrip("/") or relative.startswith(pattern.rstrip("/") + "/")
               or fnmatch.fnmatchcase(relative, pattern) for pattern in patterns)


def _python_files(root, source_root, exclude):
    if root.is_file():
        return (root,) if root.suffix == ".py" and not _excluded(source_root, root, exclude) else ()
    paths = []
    for directory, dirs, files in os.walk(str(root), followlinks=False):
        dirs[:] = sorted(d for d in dirs if d not in ("__pycache__", ".venv", "venv")
                         and not Path(directory, d).is_symlink()
                         and not _excluded(source_root, Path(directory, d), exclude))
        paths.extend(Path(directory, name) for name in files if name.endswith(".py")
                     and not _excluded(source_root, Path(directory, name), exclude))
    return paths


def _candidate_modules(source_root, roots, exclude=()):
    candidates = {}
    for root in roots:
        if not root.exists():
            raise ValueError("scan root does not exist: %s" % root)
        if root.is_symlink():
            raise ValueError("scan root must not be a symlink: %s" % root)
        resolved = root.resolve()
        if resolved != source_root and source_root not in resolved.parents:
            raise ValueError("scan root must be inside source root: %s" % root)
        if _excluded(source_root, resolved, exclude):
            continue
        for path in sorted(_python_files(resolved, source_root, exclude)):
            if path.is_symlink():
                continue
            classes, required, probe = _source_classes(path)
            if not classes and not probe:
                continue
            name = _module_name(source_root, path)
            if not name:
                raise ValueError("source root __init__.py has no importable identity; use its parent as --source-root")
            prior = candidates.get(name)
            alternative = (path.parent.with_suffix(".py") if path.name == "__init__.py"
                           else path.with_suffix("") / "__init__.py")
            if (prior is not None and prior[0] != str(path)) or (path.name != "__init__.py" and alternative.is_file()):
                raise ValueError("multiple files map to module %s" % name)
            candidates[name] = (str(path), sorted(classes), sorted(required))
    return sorted(candidates.items())


def _blocked_input(*args, **kwargs):
    raise UnsafeImportError("terminal input is unavailable during dataclass discovery")


class _BlockedStdin:
    read = readline = readlines = _blocked_input
    def __iter__(self):
        return self
    def __next__(self):
        return _blocked_input()


def _worker(source_root, candidates):
    sys.dont_write_bytecode = True
    builtins.input = _blocked_input
    sys.stdin = _BlockedStdin()
    sys.path.insert(0, source_root)
    native_dataclass, native_field = dataclasses.dataclass, dataclasses.field
    scoped_modules = {name for name, _ in candidates}
    # Retain each Field object as well as its id, avoiding id reuse after collection.
    explicit_fields = {}

    def checked_dataclass(cls=None, **kwargs):
        if cls is None:
            return lambda target: checked_dataclass(target, **kwargs)
        scoped = cls.__module__ in scoped_modules
        identity = "%s.%s" % (cls.__module__, cls.__qualname__)
        if scoped:
            if "." in cls.__qualname__ or "<locals>" in cls.__qualname__:
                raise ValueError("nested and function-local dataclasses are unsupported: %s" % identity)
            if set(kwargs) - {"frozen"}:
                raise ValueError("unsupported dataclass arguments for %s: %s" %
                                 (identity, sorted(set(kwargs) - {"frozen"})))
        result = native_dataclass(cls, **kwargs)
        if scoped:
            for item in dataclasses.fields(result):
                recorded = explicit_fields.get(id(item))
                if recorded is not None and recorded[1] - {"default", "default_factory"}:
                    raise ValueError("unsupported field arguments for %s.%s: %s" %
                                     (identity, item.name, sorted(recorded[1] - {"default", "default_factory"})))
        return result

    def checked_field(*args, **kwargs):
        spec = native_field(*args, **kwargs)
        explicit_fields[id(spec)] = (spec, set(kwargs))
        return spec

    # Instrument globally, but enforce options only on scoped consumer classes/fields.
    dataclasses.dataclass, dataclasses.field = checked_dataclass, checked_field
    records = []
    for module_name, (path, classes, required) in candidates:
        module = importlib.import_module(module_name)
        if Path(module.__file__).resolve() != Path(path).resolve():
            raise ValueError("import origin differs from scanned file: %s" % module_name)
        found, seen = set(), set()
        for cls in vars(module).values():
            if (not isinstance(cls, type) or cls.__module__ != module_name or id(cls) in seen
                or "__dataclass_fields__" not in vars(cls) or not dataclasses.is_dataclass(cls)):
                continue
            seen.add(id(cls))
            name = cls.__qualname__
            if name not in classes:
                raise ValueError("native dataclass must use module-level decorator syntax: %s.%s" % (module_name, name))
            found.add(name)
            _validate_overlay_supported_dataclass(cls)
            records.append(((module_name, name), tuple(cls.__dataclass_fields__)))
        if set(required) - found:
            raise ValueError("decorated class is not a native dataclass: %s" % sorted(set(required) - found))
    return sorted(records)


def _worker_main(request_path, result_path):
    logs = io.StringIO()
    try:
        request = json.loads(Path(request_path).read_text(encoding="utf-8"))
        with contextlib.redirect_stdout(logs), contextlib.redirect_stderr(logs):
            records = _worker(request["source_root"], request["candidates"])
        payload = {"records": records}
    except (Exception, SystemExit) as error:
        payload = {"error": str(error), "type": type(error).__name__,
                   "input": isinstance(error, UnsafeImportError),
                   "traceback": traceback.format_exc(), "logs": logs.getvalue()}
    Path(result_path).write_text(json.dumps(payload), encoding="utf-8")


def discover_native_dataclasses(source_root, scan_roots, *, exclude=(), timeout=None):
    """Discover module-level dataclasses in trusted code using a fresh process.

    Relative scan roots prefer source_root; existing cwd-relative paths are a fallback.
    Exclusions are source-relative glob patterns. Isolation is not a security sandbox.
    """
    source_root = Path(source_root).resolve()
    if not source_root.is_dir():
        raise ValueError("source root must be an existing directory: %s" % source_root)
    roots = []
    for root in scan_roots:
        root = Path(root)
        if not root.is_absolute():
            beneath_source = source_root / root
            root = beneath_source if beneath_source.exists() or not root.exists() else root.absolute()
        roots.append(root)
    if not roots:
        raise ValueError("at least one explicit scan root is required")
    timeout = DISCOVERY_TIMEOUT if timeout is None else float(timeout)
    if not math.isfinite(timeout) or timeout <= 0:
        raise ValueError("timeout must be a positive finite number of seconds")
    candidates = _candidate_modules(source_root, roots, tuple(str(pattern).replace("\\", "/") for pattern in exclude))
    if not candidates:
        return ()
    package_path = str(Path(__file__).resolve().parents[1])
    bootstrap = ("import sys; sys.path.insert(0, %r); "
                 "from portable_dataclass_metadata.generator import _worker_main; "
                 "_worker_main(sys.argv[1], sys.argv[2])") % package_path
    # System temp permits read-only consumer trees and parents.
    with tempfile.TemporaryDirectory(prefix=".dataclass-discovery-") as temp:
        request_path, result_path = Path(temp) / "request.json", Path(temp) / "result.json"
        request_path.write_text(json.dumps({"source_root": str(source_root), "candidates": candidates}), encoding="utf-8")
        try:
            result = subprocess.run([sys.executable, "-B", "-c", bootstrap, str(request_path), str(result_path)],
                                    stdin=subprocess.DEVNULL, capture_output=True, text=True, timeout=timeout)
        except subprocess.TimeoutExpired:
            raise ValueError("dataclass discovery exceeded %s seconds" % timeout) from None
        diagnostics = (result.stdout + result.stderr).strip()
        if result.returncode:
            raise ValueError("dataclass discovery process failed (%s): %s" % (result.returncode, diagnostics))
        try:
            payload = json.loads(result_path.read_text(encoding="utf-8"))
        except (OSError, ValueError):
            raise ValueError("dataclass discovery returned invalid output: %s" % diagnostics) from None
        if "error" in payload:
            error_type = UnsafeImportError if payload.get("input") else ValueError
            message = payload["error"]
            if payload["type"] not in ("ValueError", "UnsafeImportError"):
                message = payload["type"] + ": " + message
            details = "\n".join(part for part in (payload.get("logs", "").strip(), diagnostics) if part)
            if details:
                message += "\n" + details
            raise error_type(message)
        return tuple((tuple(key), tuple(fields)) for key, fields in payload["records"])


def _validate_overlay_supported_dataclass(cls):
    qualified_name = "%s.%s" % (
        getattr(cls, "__module__", "<unknown>"),
        getattr(cls, "__qualname__", cls.__name__),
    )
    all_fields = getattr(cls, "__dataclass_fields__", {})
    fields = dataclasses.fields(cls)
    if len(fields) != len(all_fields):
        raise ValueError(
            "ClassVar and InitVar are unsupported by the MicroPython overlay: %s"
            % qualified_name
        )

    params = cls.__dataclass_params__
    if not params.eq or params.order or not params.init or not params.repr or params.unsafe_hash:
        raise ValueError(
            "unsupported dataclass options for the MicroPython overlay: %s"
            % qualified_name
        )

    for item in fields:
        if item.name not in vars(cls) and item.default_factory is dataclasses.MISSING:
            for base in cls.__mro__[1:]:
                prior = getattr(base, "__dataclass_fields__", {}).get(item.name)
                if prior is not None and prior.default_factory is not dataclasses.MISSING:
                    raise ValueError(
                        "removing an inherited default_factory is unsupported: %s.%s"
                        % (qualified_name, item.name)
                    )
        if not item.init:
            reason = "init=False"
        elif getattr(item, "kw_only", False):
            reason = "keyword-only fields"
        elif not item.compare:
            reason = "compare=False"
        elif not item.repr or item.hash is not None or item.metadata:
            reason = "unsupported field repr/hash/metadata"
        else:
            continue
        raise ValueError(
            "%s is unsupported by the MicroPython overlay: %s"
            % (reason, qualified_name)
        )


def build_manifest(records):
    manifest = {}
    for key, field_names in records:
        if (
            not isinstance(key, tuple)
            or len(key) != 2
            or not all(isinstance(part, str) and part for part in key)
        ):
            raise ValueError("invalid dataclass manifest identity: %r" % (key,))
        if not isinstance(field_names, (tuple, list)):
            raise ValueError("field names must be an ordered tuple or list: %r" % (key,))
        names = tuple(field_names)
        if not all(isinstance(name, str) and name for name in names):
            raise ValueError("invalid field names for manifest key: %r" % (key,))
        if len(names) != len(set(names)):
            raise ValueError("invalid field names for manifest key: %r" % (key,))
        if key in manifest:
            raise ValueError("duplicate dataclass manifest key: %r" % (key,))
        manifest[key] = names
    return manifest


def render_manifest(records):
    manifest = build_manifest(records)
    lines = [
        '"""Generated MicroPython dataclass field metadata. Do not edit by hand."""',
        "",
        'IDENTITY_MODE = "qualified_name"',
        "",
        "FIELD_MANIFEST = {",
    ]
    for (module_name, qualified_name), field_names in sorted(manifest.items()):
        lines.append(
            "    (%r, %r): %r," % (module_name, qualified_name, field_names)
        )
    lines.extend(("}", ""))
    return "\n".join(lines)


def write_manifest(records, output_path):
    """Write a complete manifest atomically after all discovery has succeeded."""
    output_path = Path(output_path)
    content = render_manifest(records)
    output_path.parent.mkdir(parents=True, exist_ok=True)
    temporary_path = None
    try:
        candidate_path = output_path.parent / (output_path.name + "." + secrets.token_hex(12) + ".tmp")
        descriptor = os.open(str(candidate_path), os.O_WRONLY | os.O_CREAT | os.O_EXCL, 0o666)
        temporary_path = candidate_path
        with os.fdopen(descriptor, "w", encoding="utf-8", newline="\n") as stream:
            stream.write(content)
            stream.flush()
            os.fsync(stream.fileno())
        if output_path.exists():
            mode = stat.S_IMODE(output_path.stat().st_mode)
            os.chmod(str(temporary_path), mode)
        os.replace(str(temporary_path), str(output_path))
    finally:
        if temporary_path is not None and temporary_path.exists():
            temporary_path.unlink()


def manifest_is_current(records, output_path):
    try:
        current = Path(output_path).read_text(encoding="utf-8")
    except (OSError, UnicodeError):
        return False
    return current == render_manifest(records)


def main(argv=None):
    parser = argparse.ArgumentParser(
        description="Generate a MicroPython dataclass field manifest."
    )
    parser.add_argument("--source-root", required=True, type=Path)
    parser.add_argument(
        "--scan-root",
        required=True,
        action="append",
        type=Path,
        help="directory or module file below --source-root; repeat as needed",
    )
    parser.add_argument("--output", required=True, type=Path)
    parser.add_argument("--check", action="store_true")
    parser.add_argument("--exclude", action="append", default=[], help="source-relative glob or directory to omit; repeat as needed")
    parser.add_argument("--timeout", type=float, help="discovery timeout in seconds (default: 30)")
    args = parser.parse_args(argv)

    try:
        records = discover_native_dataclasses(args.source_root, args.scan_root, exclude=args.exclude, timeout=args.timeout)
        if args.check:
            if not manifest_is_current(records, args.output):
                print("stale dataclass manifest: %s" % args.output)
                return 1
            print("dataclass manifest is current: %s entries" % len(records))
            return 0
        write_manifest(records, args.output)
        print("generated dataclass manifest: %s entries" % len(records))
        return 0
    except (Exception, SystemExit) as error:
        print("dataclass manifest error: %s" % error, file=sys.stderr)
        return 2


if __name__ == "__main__":
    raise SystemExit(main())
