"""Emit test checks as explicit raises, independent of Python optimization flags."""

import ast


class _ExplicitChecks(ast.NodeTransformer):
    def visit_Assert(self, node):
        return ast.copy_location(ast.If(
            test=ast.UnaryOp(op=ast.Not(), operand=node.test),
            body=[ast.Raise(exc=ast.Call(
                func=ast.Name(id='AssertionError', ctx=ast.Load()),
                args=[node.msg or ast.Constant(value='check failed at line %s' % node.lineno)],
                keywords=[],
            ), cause=None)],
            orelse=[],
        ), node)


def checked_source(source):
    return ast.unparse(ast.fix_missing_locations(_ExplicitChecks().visit(ast.parse(source))))
