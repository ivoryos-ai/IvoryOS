"""Workflow expressions: the conditions of if and while steps, and the statements of variable and math steps.

These were run with ``eval`` and no builtins, which still let a saved or imported workflow reach any Python object
through attributes such as ``().__class__.__base__.__subclasses__()``. ``evaluate`` reads the same expressions from
their syntax tree instead: literals, names, arithmetic, comparisons, ``and``/``or``/``not``, ``x if c else y``,
indexing and slicing, f-strings, and public attributes and methods of a value (``#result['yield']``,
``#name.upper()``). Anything else is refused: imports, function calls such as ``len(x)`` (no builtins were ever
available), lambdas, comprehensions, assignments, and any name or attribute starting with an underscore.
"""

import ast
import inspect
import operator

_BINARY = {
    ast.Add: operator.add, ast.Sub: operator.sub, ast.Mult: operator.mul, ast.Div: operator.truediv,
    ast.FloorDiv: operator.floordiv, ast.Mod: operator.mod, ast.Pow: operator.pow,
    ast.BitAnd: operator.and_, ast.BitOr: operator.or_, ast.BitXor: operator.xor,
}
_UNARY = {ast.UAdd: operator.pos, ast.USub: operator.neg, ast.Not: operator.not_, ast.Invert: operator.invert}
_COMPARE = {
    ast.Eq: operator.eq, ast.NotEq: operator.ne, ast.Lt: operator.lt, ast.LtE: operator.le,
    ast.Gt: operator.gt, ast.GtE: operator.ge, ast.Is: operator.is_, ast.IsNot: operator.is_not,
    ast.In: lambda a, b: a in b, ast.NotIn: lambda a, b: a not in b,
}
_CONVERSIONS = {-1: lambda v: v, ord("s"): str, ord("r"): repr, ord("a"): ascii}
# public names that still lead to a frame's globals or read attributes through a format string
_REFUSED_ATTRIBUTES = {
    "format", "format_map", "mro",
    "gi_frame", "gi_code", "cr_frame", "cr_code", "ag_frame", "ag_code",
    "f_back", "f_builtins", "f_code", "f_globals", "f_locals", "tb_frame", "tb_next",
}


def evaluate(expression, names=None):
    """The value of a workflow expression, with ``names`` as its variables; ValueError for what is not allowed."""
    tree = ast.parse(expression.strip(), mode="eval")
    return _Evaluator(names or {}).visit(tree.body)


class _Evaluator:
    def __init__(self, names):
        self.names = names

    def visit(self, node):
        method = getattr(self, f"visit_{type(node).__name__}", None)
        if method is None:
            raise ValueError(f"{type(node).__name__} is not allowed in a workflow expression")
        return method(node)

    def visit_Constant(self, node):
        return node.value

    # the trees of Python 3.7 and 3.8
    visit_NameConstant = visit_Constant

    def visit_Num(self, node):
        return node.n

    def visit_Str(self, node):
        return node.s

    def visit_Index(self, node):
        return self.visit(node.value)

    def visit_Name(self, node):
        if node.id.startswith("_"):
            raise ValueError(f"'{node.id}': names starting with an underscore are not allowed")
        if node.id not in self.names:
            raise NameError(f"name '{node.id}' is not defined")
        return self.names[node.id]

    def visit_BinOp(self, node):
        op = _BINARY.get(type(node.op))
        if op is None:
            raise ValueError(f"{type(node.op).__name__} is not allowed in a workflow expression")
        return op(self.visit(node.left), self.visit(node.right))

    def visit_UnaryOp(self, node):
        return _UNARY[type(node.op)](self.visit(node.operand))

    def visit_BoolOp(self, node):
        # and/or stop early and give back an operand, as in Python
        value = None
        for operand in node.values:
            value = self.visit(operand)
            if isinstance(node.op, ast.And) != bool(value):
                return value
        return value

    def visit_Compare(self, node):
        left = self.visit(node.left)
        for op, comparator in zip(node.ops, node.comparators):
            right = self.visit(comparator)
            if not _COMPARE[type(op)](left, right):
                return False
            left = right
        return True

    def visit_IfExp(self, node):
        return self.visit(node.body) if self.visit(node.test) else self.visit(node.orelse)

    def visit_Subscript(self, node):
        return self.visit(node.value)[self.visit(node.slice)]

    def visit_Slice(self, node):
        return slice(*(None if part is None else self.visit(part) for part in (node.lower, node.upper, node.step)))

    def visit_Attribute(self, node):
        value = self.visit(node.value)
        if node.attr.startswith("_") or node.attr in _REFUSED_ATTRIBUTES:
            raise ValueError(f"'.{node.attr}' is not allowed in a workflow expression")
        if inspect.ismodule(value):
            raise ValueError(f"'{value.__name__}.{node.attr}': modules are not allowed in a workflow expression")
        return getattr(value, node.attr)

    def visit_Call(self, node):
        # only a value's own methods, such as #name.upper(): there are no functions to call
        if not isinstance(node.func, ast.Attribute):
            raise ValueError("only methods of a value can be called in a workflow expression")
        method = self.visit(node.func)
        args = [self.visit(arg) for arg in node.args]
        kwargs = {}
        for keyword in node.keywords:
            if keyword.arg is None:
                raise ValueError("** is not allowed in a workflow expression")
            kwargs[keyword.arg] = self.visit(keyword.value)
        return method(*args, **kwargs)

    def visit_List(self, node):
        return [self.visit(item) for item in node.elts]

    def visit_Tuple(self, node):
        return tuple(self.visit(item) for item in node.elts)

    def visit_Set(self, node):
        return {self.visit(item) for item in node.elts}

    def visit_Dict(self, node):
        if any(key is None for key in node.keys):
            raise ValueError("** is not allowed in a workflow expression")
        return {self.visit(key): self.visit(value) for key, value in zip(node.keys, node.values)}

    def visit_JoinedStr(self, node):
        return "".join(str(self.visit(part)) for part in node.values)

    def visit_FormattedValue(self, node):
        value = _CONVERSIONS[node.conversion](self.visit(node.value))
        spec = self.visit(node.format_spec) if node.format_spec is not None else ""
        return format(value, spec)
