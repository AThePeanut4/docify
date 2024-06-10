#!/usr/bin/env python3

import importlib
import inspect
import os
import textwrap
import warnings
from argparse import ArgumentParser
from types import ModuleType

import libcst as cst
import libcst.metadata as meta

IGNORE_MODULES = ("antigravity", "this")

VERBOSE = False


def print_v(s):
    if VERBOSE:
        print(f"VERBOSE: {s}")


def print_i(s):
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

    # if __doc__ is a descriptor, it means __doc__ is an instance attribute (property)
    # and not an attribute of this actual class object
    # e.g. types.BuiltinFunctionType, aka builtin_function_or_method,
    # or typing._SpecialForm
    if inspect.isdatadescriptor(doc):
        print_i(f"ignoring __doc__ descriptor for {qualname}")
        return None

    return doc


def get_doc_def(scope_obj: object, obj: object, qualname: str, name: str):
    if (
        inspect.isbuiltin(obj)
        or inspect.isfunction(obj)
        or inspect.ismethod(obj)
        or inspect.isbuiltin(obj)
        or inspect.ismethoddescriptor(obj)
        or inspect.ismethodwrapper(obj)
        or inspect.isdatadescriptor(obj)
    ):
        doc = getattr(obj, "__doc__", None)

        if inspect.isclass(scope_obj) and scope_obj != object:
            if name == "__init__" and doc == object.__init__.__doc__:
                print_v(f"ignoring __doc__ for {qualname}")
                return None
            elif name == "__new__" and doc == object.__new__.__doc__:
                print_v(f"ignoring __doc__ for {qualname}")
                return None

        return doc
    else:
        # try to get the descriptor for the object, and get __doc__ from that
        # this allows to get the docstring for e.g. object.__class__
        raw_obj = scope_obj.__dict__.get(name)
        if inspect.isdatadescriptor(raw_obj):
            doc = getattr(raw_obj, "__doc__", None)
            if doc:
                print_i(f"using __doc__ from descriptor for {qualname}")
                return doc

        if not inspect.isclass(obj):
            # obj is an object (instance of a class)
            # only get __doc__ if it is defined as an instance attribute
            # rather than a class attribute,
            # or if it is defined as an instance descriptor (property)
            raw_doc = type(obj).__dict__.get("__doc__")
            if raw_doc is None or inspect.isdatadescriptor(raw_doc):
                doc = getattr(obj, "__doc__", None)
                if doc:
                    print_i(f"using __doc__ from class instance {qualname}")
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


# TODO: somehow add module attribute docstrings? e.g. typing.Union
# TODO: infer for renamed classes, e.g. types._Cell is CellType at runtime, and CellType = _Cell exists in stub


class Transformer(cst.CSTTransformer):
    def __init__(self, import_path: str, mod: ModuleType, wrapper: cst.MetadataWrapper):
        self.import_path = import_path
        self.mod = mod
        self.scope_map = wrapper.resolve(meta.ScopeProvider)
        self.parent_map = wrapper.resolve(meta.ParentNodeProvider)

    def leave_ClassFunctionDef(
        self,
        original_node: cst.ClassDef | cst.FunctionDef,
        updated_node: cst.ClassDef | cst.FunctionDef,
    ):
        scope = self.scope_map[original_node]
        if scope is None:
            return updated_node

        name = original_node.name.value
        qualname = get_qualname(scope, name)

        r = get_obj(self.mod, qualname)
        if r is None:
            print_v(f"cannot find {qualname}")
            return updated_node

        scope_obj, obj = r

        if isinstance(original_node, cst.FunctionDef):
            doc = get_doc_def(scope_obj, obj, qualname, name)
        elif isinstance(original_node, cst.ClassDef):
            doc = get_doc_class(obj, qualname)
        else:
            doc = None

        if doc is not None:
            if type(doc) != str:
                print_w(f"__doc__ for {qualname} is {type(doc)!r}, not str")
                doc = None
            else:
                doc = inspect.cleandoc(doc)

        if not doc:
            print_v(f"could not find __doc__ for {qualname}")
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

                n = self.parent_map.get(n, None)

        doc = docquote_str(doc, indent)
        print_v(f"__doc__ for {qualname}:\n{doc}")

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
        doc = getattr(self.mod, "__doc__", None)
        if not doc:
            print_v(f"could not find __doc__ for {self.import_path}")
            return updated_node

        doc = inspect.cleandoc(doc)
        doc = docquote_str(doc)
        print_v(f"__doc__ for {self.import_path}:\n{doc}")

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


def main():
    arg_parser = ArgumentParser()
    arg_parser.add_argument(
        "-v",
        "--verbose",
        action="store_true",
        help="print verbose output",
    )
    arg_parser.add_argument(
        "input_dir",
        metavar="INPUT_DIR",
        help="directory to read stubs from",
    )
    arg_parser.add_argument(
        "output_dir",
        metavar="OUTPUT_DIR",
        help="directory to write modified stubs to",
    )

    args = arg_parser.parse_args()

    global VERBOSE
    VERBOSE = args.verbose

    # accessing docstrings for deprecated classes/functions gives DeprecationWarnings
    warnings.simplefilter("ignore", DeprecationWarning)

    os.makedirs(args.output_dir, exist_ok=True)

    for base_dir, _, files in os.walk(args.input_dir):
        for input_filename in files:
            input_path = os.path.join(base_dir, input_filename)
            file_relpath = os.path.relpath(input_path, args.input_dir)

            import_path, file_ext = os.path.splitext(file_relpath)
            if file_ext != ".pyi":
                continue

            import_path = import_path.replace(os.path.sep, ".")
            import_path = import_path.removesuffix(".__init__")

            if import_path in IGNORE_MODULES:
                continue

            try:
                mod = importlib.import_module(import_path)
            except ModuleNotFoundError:
                print_w(f"could not import {import_path}, module not found")
                continue
            except ImportError as e:
                print_e(f"could not import {import_path}, {e}")
                continue

            with open(input_path, "r") as f:
                stub_source = f.read()

            try:
                stub_cst = cst.parse_module(stub_source)
            except Exception as e:
                print_e(f"could not parse {file_relpath}: {e}")
                continue

            print_i(f"processing {file_relpath}")

            wrapper = cst.MetadataWrapper(stub_cst)
            visitor = Transformer(import_path, mod, wrapper)

            new_stub_cst = wrapper.module.visit(visitor)

            output_path = os.path.join(args.output_dir, file_relpath)
            os.makedirs(os.path.dirname(output_path), exist_ok=True)

            with open(output_path, "w") as f:
                f.write(new_stub_cst.code)


if __name__ == "__main__":
    main()
