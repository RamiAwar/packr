import ast
import collections

Module = collections.namedtuple("Module", ["name", "try_", "file", "lineno", "alias"])


class ImportsParser:
    def __init__(self, rawcode_callback=None):
        self._modules = []
        self._rawcode_callback = rawcode_callback

    def parse(self, content, fpath, lineno):
        parsed = ast.parse(content)
        self._fpath = fpath
        self._mods = fpath[:-3].split("/")
        self._lineno = lineno - 1
        self.visit(parsed)

    def _add_module(self, name, try_, lineno, alias):
        self._modules.append(
            Module(name=name, try_=try_, file=self._fpath, lineno=lineno, alias=alias)
        )

    def _add_rawcode(self, code, lineno):
        if self._rawcode_callback:
            self._rawcode_callback(code, lineno)

    def visit_Import(self, node, try_=False):
        """As we know: `import a [as b]`."""
        lineno = node.lineno + self._lineno
        for alias in node.names:
            self._add_module(alias.name, try_, lineno, alias.name)

    def visit_ImportFrom(self, node, try_=False):
        """
        As we know: `from a import b [as c]`. If node.level is not 0,
        import statement like this `from .a import b`.
        """

        mod_name = node.module
        level = node.level
        if mod_name is None:
            level -= 1
            mod_name = ""
        for alias in node.names:
            name = mod_name
            if level > 0 or mod_name == "":
                name = level * "." + mod_name + "." + alias.name
            lineno = node.lineno + self._lineno
            self._add_module(name, try_, lineno, alias.name)

    def visit_TryExcept(self, node):
        """
        If modules which imported by `try except` and not found,
        maybe them come from other Python version.
        """
        for ipt in node.body:
            if ipt.__class__.__name__.startswith("Import"):
                method = "visit_" + ipt.__class__.__name__
                getattr(self, method)(ipt, True)
        for handler in node.handlers:
            for ipt in handler.body:
                if ipt.__class__.__name__.startswith("Import"):
                    method = "visit_" + ipt.__class__.__name__
                    getattr(self, method)(ipt, True)

    # For Python 3.3+
    visit_Try = visit_TryExcept

    def visit_Exec(self, node):
        """
        Check `expression` of `exec(expression[, globals[, locals]])`.
        **Just available in python 2.**
        """
        if hasattr(node.body, "s"):
            self._add_rawcode(node.body.s, node.lineno + self._lineno)
        # PR#13: https://github.com/damnever/pigar/pull/13
        # Sometimes exec statement may be called with tuple in Py2.7.6
        elif (
            hasattr(node.body, "elts")
            and len(node.body.elts) >= 1
            and hasattr(node.body.elts[0], "s")
        ):
            self._add_rawcode(node.body.elts[0].s, node.lineno + self._lineno)

    def visit_Expr(self, node):
        """
        Check `expression` of `eval(expression[, globals[, locals]])`.
        Check `expression` of `exec(expression[, globals[, locals]])`
        in python 3.
        Check `name` of `__import__(name[, globals[, locals[,
        fromlist[, level]]]])`.
        Check `name` or `package` of `importlib.import_module(name,
        package=None)`.
        """
        # Built-in functions
        value = node.value
        if isinstance(value, ast.Call):
            lineno = node.lineno + self._lineno
            if hasattr(value.func, "id"):
                if value.func.id == "eval" and hasattr(node.value.args[0], "s"):
                    self._add_rawcode(node.value.args[0].s, lineno)
                # **`exec` function in Python 3.**
                elif value.func.id == "exec" and hasattr(node.value.args[0], "s"):
                    self._add_rawcode(node.value.args[0].s, lineno)
                # `__import__` function.
                elif (
                    value.func.id == "__import__"
                    and len(node.value.args) > 0
                    and hasattr(node.value.args[0], "s")
                ):
                    self._add_module(node.value.args[0].s, False, lineno)
            # `import_module` function.
            elif getattr(value.func, "attr", "") == "import_module":
                module = getattr(value.func, "value", None)
                if module is not None and getattr(module, "id", "") == "importlib":
                    args = node.value.args
                    arg_len = len(args)
                    if arg_len > 0 and hasattr(args[0], "s"):
                        name = args[0].s
                        if not name.startswith("."):
                            self._add_module(name, False, lineno)
                        elif arg_len == 2 and hasattr(args[1], "s"):
                            self._add_module(args[1].s, False, lineno)

    def visit(self, node):
        """Visit a node, no recursively."""
        for node in ast.walk(node):
            method = "visit_" + node.__class__.__name__
            getattr(self, method, lambda x: x)(node)

    @property
    def modules(self):
        return self._modules
