#!/usr/bin/env python3

from __future__ import annotations

import importlib
import inspect
import os
import shutil
import sys
import textwrap
import warnings
from argparse import ArgumentParser
from tempfile import NamedTemporaryFile
from types import ModuleType
from typing import Literal, Sequence, cast

import libcst as cst
import libcst.matchers as m
import libcst.metadata as meta

IGNORE_MODULES = ("antigravity", "this")

VERBOSITY = 0


def print_t(s):
    if VERBOSITY > 2:
        print(f"TRACE: {s}")


def print_v(s):
    if VERBOSITY > 1:
        print(f"VERBOSE: {s}")


def print_i(s):
    if VERBOSITY > 0:
        print(f"INFO: {s}")


def print_w(s):
    print(f"WARNING: {s}")


def print_e(s):
    print(f"ERROR: {s}")


def get_obj(mod: ModuleType, qualname: str) -> tuple[object, object] | None:
    scope_obj = None
    obj = mod
    try:
        for part in qualname.split("."):
            scope_obj = obj
            obj = getattr(scope_obj, part)
    except AttributeError:
        return None
    return scope_obj, obj


def get_qualname(scope: meta.Scope, name: str):
    qualname = name
    while True:
        if isinstance(scope, meta.GlobalScope):
            return qualname
        elif isinstance(scope, meta.ClassScope):
            if not scope.name:
                raise ValueError
            qualname = f"{scope.name}.{qualname}"
        else:
            raise TypeError
        scope = scope.parent


def get_doc_class(obj: object, qualname: str):
    doc = getattr(obj, "__doc__", None)

    # ignore if __doc__ is a data descriptor (property)
    # e.g. types.BuiltinFunctionType, aka builtin_function_or_method,
    # or typing._SpecialForm
    if inspect.isdatadescriptor(doc):
        print_v(f"ignoring __doc__ descriptor for {qualname}")
        return None

    return doc


def get_doc_def(scope_obj: object, obj: object, qualname: str, name: str):
    if inspect.isroutine(obj) or inspect.isdatadescriptor(obj):
        # for functions, methods and data descriptors, get __doc__ directly
        doc = getattr(obj, "__doc__", None)

        # ignore __init__ and __new__ if they are inherited from object
        if inspect.isclass(scope_obj) and scope_obj != object:
            if name == "__init__" and doc == object.__init__.__doc__:
                print_t(f"ignoring __doc__ for {qualname}")
                return None
            elif name == "__new__" and doc == object.__new__.__doc__:
                print_t(f"ignoring __doc__ for {qualname}")
                return None

        return doc

    # try to get the descriptor for the object, and get __doc__ from that
    # this allows to get the docstring for e.g. object.__class__
    raw_obj = scope_obj.__dict__.get(name)
    if inspect.isdatadescriptor(raw_obj):
        doc = getattr(raw_obj, "__doc__", None)
        if doc:
            print_v(f"using __doc__ from descriptor for {qualname}")
            return doc

    if not inspect.isclass(obj):
        # obj is an object (instance of a class)
        # only get __doc__ if it is an attribute of the instance
        # rather than the class, or if it is a data descriptor (property)
        raw_doc = type(obj).__dict__.get("__doc__")
        if raw_doc is None or inspect.isdatadescriptor(raw_doc):
            doc = getattr(obj, "__doc__", None)
            if doc:
                print_v(f"using __doc__ from class instance {qualname}")
                return doc

    return None


def docquote_str(doc: str, indent: str = ""):
    # if unprintable while ignoring newlines, just use repr()
    if not doc.replace("\n", "").isprintable():
        return repr(doc)

    raw = "\\" in doc

    if "\n" in doc:
        doc = textwrap.indent(doc, indent)
        doc = "\n" + doc + "\n" + indent
    elif doc[-1:] == '"':
        if raw:
            # raw strings cannot end in a ", so just add a space
            doc = doc + " "
        else:
            # escape the "
            doc = doc[:-1] + '\\"'

    # no docstring should really have """, but let's be safe
    if raw:
        # escapes don't work in raw strings, replace with '''
        doc = doc.replace('"""', "'''")
    else:
        doc = doc.replace('"""', '\\"\\"\\"')

    return ('r"""' if raw else '"""') + doc + '"""'


def get_version(elements: Sequence[cst.BaseElement]):
    return tuple(int(cast(cst.Integer, element.value).value) for element in elements)


class ConditionProvider(meta.BatchableMetadataProvider[bool]):
    def leave_Comparison(self, original_node):
        if m.matches(
            original_node,
            m.Comparison(
                left=m.Attribute(
                    m.Name("sys"),
                    m.Name("version_info"),
                ),
                comparisons=[
                    m.ComparisonTarget(
                        m.GreaterThanEqual()
                        | m.GreaterThan()
                        | m.Equal()
                        | m.NotEqual()
                        | m.LessThan()
                        | m.LessThanEqual(),
                        comparator=m.Tuple(
                            [
                                m.Element(m.Integer()),
                                m.AtMostN(m.Element(m.Integer()), n=2),
                            ]
                        ),
                    )
                ],
            ),
        ):
            matches = m.matches(
                original_node,
                m.Comparison(
                    comparisons=[
                        m.ComparisonTarget(
                            m.GreaterThanEqual(),
                            comparator=m.Tuple(
                                m.MatchIfTrue(
                                    lambda els: sys.version_info >= get_version(els)
                                ),
                            ),
                        )
                        | m.ComparisonTarget(
                            m.GreaterThan(),
                            comparator=m.Tuple(
                                m.MatchIfTrue(
                                    lambda els: sys.version_info > get_version(els)
                                ),
                            ),
                        )
                        | m.ComparisonTarget(
                            m.Equal(),
                            comparator=m.Tuple(
                                m.MatchIfTrue(
                                    lambda els: sys.version_info == get_version(els)
                                ),
                            ),
                        )
                        | m.ComparisonTarget(
                            m.NotEqual(),
                            comparator=m.Tuple(
                                m.MatchIfTrue(
                                    lambda els: sys.version_info != get_version(els)
                                ),
                            ),
                        )
                        | m.ComparisonTarget(
                            m.LessThan(),
                            comparator=m.Tuple(
                                m.MatchIfTrue(
                                    lambda els: sys.version_info < get_version(els)
                                ),
                            ),
                        )
                        | m.ComparisonTarget(
                            m.LessThanEqual(),
                            comparator=m.Tuple(
                                m.MatchIfTrue(
                                    lambda els: sys.version_info <= get_version(els)
                                ),
                            ),
                        )
                    ]
                ),
            )
            self.set_metadata(original_node, matches)

        if m.matches(
            original_node,
            m.Comparison(
                left=m.Attribute(
                    m.Name("sys"),
                    m.Name("platform"),
                ),
                comparisons=[
                    m.ComparisonTarget(
                        m.Equal() | m.NotEqual(),
                        comparator=m.SimpleString(),
                    )
                ],
            ),
        ):
            matches = m.matches(
                original_node,
                m.Comparison(
                    comparisons=[
                        m.ComparisonTarget(
                            m.Equal(),
                            comparator=m.MatchIfTrue(lambda val: sys.platform == val),
                        )
                        | m.ComparisonTarget(
                            m.NotEqual(),
                            comparator=m.MatchIfTrue(lambda val: sys.platform != val),
                        )
                    ]
                ),
            )
            self.set_metadata(original_node, matches)

    def leave_UnaryOperation(self, original_node):
        val = self.get_metadata(type(self), original_node.expression, None)
        if val is None:
            return

        if isinstance(original_node.operator, cst.Not):
            self.set_metadata(original_node, not val)

    def leave_BooleanOperation(self, original_node):
        left = self.get_metadata(type(self), original_node.left, None)
        if left is None:
            return

        right = self.get_metadata(type(self), original_node.right, None)
        if right is None:
            return

        if isinstance(original_node.operator, cst.And):
            self.set_metadata(original_node, left and right)
        elif isinstance(original_node.operator, cst.Or):
            self.set_metadata(original_node, left or right)


class UnreachableProvider(meta.BatchableMetadataProvider[Literal[True]]):
    METADATA_DEPENDENCIES = [ConditionProvider]

    class SetMetadataVisitor(cst.CSTVisitor):
        def __init__(self, provider: "UnreachableProvider"):
            super().__init__()
            self.provider = provider

        def on_leave(self, original_node):
            self.provider.set_metadata(original_node, True)
            super().on_leave(original_node)

    def mark_unreachable(self, node: cst.If | cst.Else):
        self.set_metadata(node, True)
        node.body.visit(self.SetMetadataVisitor(self))

    def visit_If(self, node):
        cond = self.get_metadata(type(self), node, None)
        if cond is not None:
            return

        cond = self.get_metadata(ConditionProvider, node.test, None)
        if cond is None:
            print_w(f"encountered unsupported condition:\n{node.test}")
            return

        if cond:
            # condition is true - subsequent branches are unreachable
            while True:
                node = node.orelse
                if node is None:
                    break
                elif isinstance(node, cst.If):
                    self.mark_unreachable(node)
                elif isinstance(node, cst.Else):
                    self.mark_unreachable(node)
                    break
        else:
            # condition is false - this branch is unreachable
            self.mark_unreachable(node)


# TODO: somehow add module attribute docstrings? e.g. typing.Union
# TODO: infer for renamed classes, e.g. types._Cell is CellType at runtime, and CellType = _Cell exists in stub


class Transformer(cst.CSTTransformer):
    METADATA_DEPENDENCIES = [
        meta.ScopeProvider,
        meta.ParentNodeProvider,
        UnreachableProvider,
    ]

    def __init__(self, import_path: str, mod: ModuleType):
        super().__init__()
        self.import_path = import_path
        self.mod = mod

    def leave_ClassFunctionDef(
        self,
        original_node: cst.ClassDef | cst.FunctionDef,
        updated_node: cst.ClassDef | cst.FunctionDef,
    ):
        scope = self.get_metadata(meta.ScopeProvider, original_node, None)
        if scope is None:
            return updated_node

        if self.get_metadata(UnreachableProvider, original_node, False):
            return updated_node

        name = original_node.name.value
        qualname = get_qualname(scope, name)

        if m.matches(
            updated_node.body,
            m.SimpleStatementSuite(
                [
                    m.Expr(m.SimpleString()),
                    m.ZeroOrMore(),
                ]
            )
            | m.IndentedBlock(
                [
                    m.SimpleStatementLine(
                        [
                            m.Expr(m.SimpleString()),
                            m.ZeroOrMore(),
                        ]
                    ),
                    m.ZeroOrMore(),
                ]
            ),
        ):
            print_t(f"docstring for {qualname} already exists, skipping")
            return updated_node

        r = get_obj(self.mod, qualname)
        if r is None:
            print_t(f"cannot find {qualname}")
            return updated_node

        scope_obj, obj = r

        if isinstance(original_node, cst.FunctionDef):
            doc = get_doc_def(scope_obj, obj, qualname, name)
        elif isinstance(original_node, cst.ClassDef):
            doc = get_doc_class(obj, qualname)
        else:
            doc = None

        if doc is not None:
            if isinstance(doc, str):
                print_w(f"__doc__ for {qualname} is {type(doc)!r}, not str")
                doc = None
            else:
                doc = inspect.cleandoc(doc)

        if not doc:
            print_t(f"could not find __doc__ for {qualname}")
            return updated_node

        indent = ""
        if "\n" in doc:
            n = original_node.body
            while n is not None:
                if isinstance(n, cst.SimpleStatementSuite):
                    indent += self.module.default_indent
                elif isinstance(n, cst.IndentedBlock):
                    block_indent = n.indent
                    if block_indent is None:
                        block_indent = self.module.default_indent
                    indent += block_indent

                n = self.get_metadata(meta.ParentNodeProvider, n, None)

        doc = docquote_str(doc, indent)
        print_t(f"__doc__ for {qualname}:\n{doc}")

        docstring_node = cst.SimpleStatementLine([cst.Expr(cst.SimpleString(doc))])

        node_body = updated_node.body
        if isinstance(node_body, cst.SimpleStatementSuite):
            lines = (cst.SimpleStatementLine([x]) for x in node_body.body)
            node_body = cst.IndentedBlock([docstring_node, *lines])
        elif isinstance(node_body, cst.IndentedBlock):
            node_body = node_body.with_changes(body=[docstring_node, *node_body.body])
        else:
            return updated_node

        return updated_node.with_changes(body=node_body)

    def leave_ClassDef(self, original_node, updated_node):
        return self.leave_ClassFunctionDef(original_node, updated_node)

    def leave_FunctionDef(self, original_node, updated_node):
        return self.leave_ClassFunctionDef(original_node, updated_node)

    def visit_Module(self, node):
        self.module = node

    def leave_Module(self, original_node, updated_node):
        if m.matches(
            updated_node,
            m.Module(
                [
                    m.SimpleStatementLine(
                        [
                            m.Expr(m.SimpleString()),
                            m.ZeroOrMore(),
                        ]
                    ),
                    m.ZeroOrMore(),
                ]
            ),
        ):
            print_t(f"docstring for {self.import_path} already exists, skipping")
            return updated_node

        doc = getattr(self.mod, "__doc__", None)
        if not doc:
            print_t(f"could not find __doc__ for {self.import_path}")
            return updated_node

        doc = inspect.cleandoc(doc)
        doc = docquote_str(doc)
        print_t(f"__doc__ for {self.import_path}:\n{doc}")

        node_body = updated_node.body
        if len(node_body) != 0:
            node_body = (
                node_body[0].with_changes(
                    leading_lines=[
                        cst.EmptyLine(),
                        *node_body[0].leading_lines,
                    ]
                ),
                *node_body[1:],
            )
        else:
            updated_node = updated_node.with_changes(
                footer=[cst.EmptyLine(), *updated_node.footer]
            )

        if len(updated_node.header) != 0:
            updated_node = updated_node.with_changes(
                header=[*updated_node.header, cst.EmptyLine()]
            )

        node_body = (
            cst.SimpleStatementLine(
                [cst.Expr(cst.SimpleString(doc))],
            ),
            *node_body,
        )
        return updated_node.with_changes(body=node_body)


def run(
    *,
    input_dir: str,
    builtins_only: bool = False,
    in_place: bool = True,
    output_dir: str = "",
):
    queue: list[tuple[str, str]] = []

    for base_dir, _, filenames in os.walk(input_dir):
        for filename in filenames:
            file_path = os.path.join(base_dir, filename)
            file_relpath = os.path.relpath(file_path, input_dir)

            import_path, file_ext = os.path.splitext(file_relpath)
            if file_ext != ".pyi":
                continue

            import_path = import_path.replace(os.path.sep, ".")
            if import_path[-9:] == ".__init__":
                import_path = import_path[:-9]

            if import_path in IGNORE_MODULES:
                continue
            if builtins_only and import_path not in sys.builtin_module_names:
                continue

            queue.append((import_path, file_relpath))

    if VERBOSITY > 0:
        from tqdm import tqdm

        # a bit hacky, but eh
        global print
        print = tqdm.write

        queue_iter = tqdm(queue, dynamic_ncols=True)
    else:
        queue_iter = queue

    with warnings.catch_warnings():
        # accessing docstrings for deprecated classes/functions gives DeprecationWarnings
        warnings.simplefilter("ignore", DeprecationWarning)

        for import_path, file_relpath in queue_iter:
            file_path = os.path.join(input_dir, file_relpath)

            try:
                mod = importlib.import_module(import_path)
            except ModuleNotFoundError:
                print_w(f"could not import {import_path}, module not found")
                continue
            except ImportError as e:
                print_e(f"could not import {import_path}, {e}")
                continue

            with open(file_path, "r") as f:
                stub_source = f.read()

            try:
                stub_cst = cst.parse_module(stub_source)
            except Exception as e:
                print_e(f"could not parse {file_relpath}: {e}")
                continue

            print_i(f"processing {file_relpath}")

            wrapper = cst.MetadataWrapper(stub_cst)
            visitor = Transformer(import_path, mod)

            new_stub_cst = wrapper.visit(visitor)

            if in_place:
                f = NamedTemporaryFile(
                    dir=input_dir,
                    prefix=file_relpath + ".",
                    mode="w",
                    delete=False,
                )
                try:
                    with f:
                        f.write(new_stub_cst.code)
                except:
                    os.remove(f.name)
                    raise

                shutil.copymode(file_path, f.name)
                os.replace(f.name, file_path)
            else:
                output_path = os.path.join(output_dir, file_relpath)
                os.makedirs(os.path.dirname(output_path), exist_ok=True)

                with open(output_path, "w") as f:
                    f.write(new_stub_cst.code)


def main(*args: str):
    arg_parser = ArgumentParser(
        description="A script to add docstrings to Python type stubs using reflection"
    )
    arg_parser.add_argument(
        "-v",
        "--verbose",
        action="count",
        default=0,
        help="increase verbosity",
    )
    arg_parser.add_argument(
        "-q",
        "--quiet",
        action="count",
        default=0,
        help="decrease verbosity",
    )
    arg_parser.add_argument(
        "-b",
        "--builtins-only",
        action="store_true",
        help="only add docstrings to modules found in `sys.builtin_module_names`",
    )
    arg_parser.add_argument(
        "input_dir",
        metavar="INPUT_DIR",
        help="directory to read stubs from",
    )
    output_group = arg_parser.add_mutually_exclusive_group(required=True)
    output_group.add_argument(
        "-i",
        "--in-place",
        action="store_true",
        help="modify stubs in-place",
    )
    output_group.add_argument(
        "-o",
        "--output",
        metavar="OUTPUT_DIR",
        dest="output_dir",
        help="directory to write modified stubs to",
    )

    parsed_args = arg_parser.parse_args(args)

    global VERBOSITY
    VERBOSITY = 1
    VERBOSITY += parsed_args.verbose
    VERBOSITY -= parsed_args.quiet

    run_args = vars(parsed_args)
    del run_args["verbose"]
    del run_args["quiet"]
    run(**run_args)


if __name__ == "__main__":
    main(*sys.argv[1:])
