"""Small bounded scalar expressions for configured variable assignments.

No eval, calls, attribute access, imports, containers or external I/O.
"""

import ast
import math
import operator


class ExpressionError(ValueError):
    """Payload-free expression failure."""


def _scalar(value):
    if value is None or type(value) in (bool, str, int, float):
        if isinstance(value, str) and len(value) > 8000:
            raise ExpressionError("expression_size")
        if type(value) is int and value.bit_length() > 4096:
            raise ExpressionError("expression_size")
        if type(value) is float and not math.isfinite(value):
            raise ExpressionError("expression_number")
        return value
    raise ExpressionError("expression_type")


def evaluate_expression(expression, facts):
    """Evaluate only the compiler's scalar AST language within fixed bounds."""
    if not isinstance(expression, str) or len(expression) > 8000:
        raise ExpressionError("expression_size")
    try:
        tree = ast.parse(expression, mode="eval")
        if sum(1 for _ in ast.walk(tree)) > 128:
            raise ExpressionError("expression_size")
        return _scalar(_evaluate(tree.body, facts, 0))
    except ExpressionError:
        raise
    except (SyntaxError, ValueError, TypeError, ArithmeticError, RecursionError):
        raise ExpressionError("expression_invalid") from None


def _evaluate(node, facts, depth):
    if depth > 24:
        raise ExpressionError("expression_depth")
    descend = lambda child: _evaluate(child, facts, depth + 1)
    if isinstance(node, ast.Constant):
        return _scalar(node.value)
    if isinstance(node, ast.Name):
        if node.id not in facts or node.id.startswith("_"):
            raise ExpressionError("expression_variable")
        return _scalar(facts[node.id])
    if isinstance(node, ast.UnaryOp):
        value = descend(node.operand)
        if isinstance(node.op, ast.Not):
            return not value
        if type(value) not in (int, float):
            raise ExpressionError("expression_type")
        if isinstance(node.op, ast.USub):
            return _scalar(-value)
        if isinstance(node.op, ast.UAdd):
            return value
    if isinstance(node, ast.BinOp):
        left, right = descend(node.left), descend(node.right)
        operations = {
            ast.Add: operator.add, ast.Sub: operator.sub, ast.Mult: operator.mul,
            ast.Div: operator.truediv, ast.FloorDiv: operator.floordiv,
            ast.Mod: operator.mod,
        }
        operation = operations.get(type(node.op))
        if operation is None or type(left) is bool or type(right) is bool:
            raise ExpressionError("expression_operator")
        if isinstance(node.op, ast.Mult):
            if isinstance(left, str) or isinstance(right, str):
                text, count = (left, right) if isinstance(left, str) else (right, left)
                if type(count) is not int or abs(count) > 8000 or len(text) * max(count, 0) > 8000:
                    raise ExpressionError("expression_size")
            elif type(left) is int and type(right) is int:
                if left.bit_length() + right.bit_length() > 4096:
                    raise ExpressionError("expression_size")
        if isinstance(node.op, ast.Add) and isinstance(left, str) and isinstance(right, str):
            if len(left) + len(right) > 8000:
                raise ExpressionError("expression_size")
        if isinstance(node.op, ast.Mod) and isinstance(left, str):
            raise ExpressionError("expression_operator")
        return _scalar(operation(left, right))
    if isinstance(node, ast.BoolOp) and isinstance(node.op, (ast.And, ast.Or)):
        value = None
        for child in node.values:
            value = descend(child)
            if isinstance(node.op, ast.And) and not value:
                break
            if isinstance(node.op, ast.Or) and value:
                break
        return value
    if isinstance(node, ast.Compare):
        operations = {
            ast.Eq: operator.eq, ast.NotEq: operator.ne, ast.Lt: operator.lt,
            ast.LtE: operator.le, ast.Gt: operator.gt, ast.GtE: operator.ge,
        }
        left = descend(node.left)
        for comparison, right_node in zip(node.ops, node.comparators):
            operation = operations.get(type(comparison))
            if operation is None:
                raise ExpressionError("expression_operator")
            right = descend(right_node)
            if not operation(left, right):
                return False
            left = right
        return True
    if isinstance(node, ast.IfExp):
        return descend(node.body if descend(node.test) else node.orelse)
    raise ExpressionError("expression_syntax")
