import ast

from .tools import OptimizerStep, pretty_dump, NodeTransformer, NodeVisitor

class Checker(NodeVisitor):
    '''Gather a list of problems that would prevent inlining a function.'''
    def __init__(self):
        self.problems = []

    def visit_Call(self, node):
        # Reject explicit attempts to use locals()
        # TODO: detect uses via other names
        if isinstance(node.func, ast.Name):
            if node.func.id == 'locals':
                self.problems.append('use of locals()')

def locate_kwarg(funcdef, name):
    '''Get the index of an argument of funcdef by name.'''
    for idx, arg in enumerate(funcdef.args.args):
        if arg.arg == name:
            return idx
    raise ValueError('argument %r not found' % name)

class RenameVisitor(NodeTransformer):
    def __init__(self, callsite, inlinable, actual_pos_args):
        assert callsite.starargs is None
        assert callsite.kwargs is None
        assert inlinable.args.vararg is None
        assert inlinable.args.kwonlyargs == []
        assert inlinable.args.kw_defaults == []
        assert inlinable.args.kwarg is None
        assert inlinable.args.defaults == []

        # Mapping from name in callee to name in caller
        self.remapping = {}
        for formal, actual in zip(inlinable.args.args, actual_pos_args):
            self.remapping[formal.arg] = actual.id

    def visit_Name(self, node):
        assert isinstance(node.ctx, ast.Load) # FIXME
        if node.id in self.remapping:
            return ast.Name(id=self.remapping[node.id], ctx=node.ctx)
        return node

class Expansion:
    '''Information about a callsite that's a candidate for inlining, giving
    the funcdef, and the actual positional arguments (having
    resolved any keyword arguments.'''
    def __init__(self, funcdef, actual_pos_args):
        self.funcdef = funcdef
        self.actual_pos_args = actual_pos_args

class InlineSubstitution(OptimizerStep):
    """Function call inlining."""

    def can_inline(self, callsite):
        '''Given a Call callsite, determine whether we should inline
        the callee.  If so, return an Expansion instance, otherwise
        return None.'''
        # TODO: size criteria?
        # TODO: don't do it for recursive functions
        if not isinstance(callsite.func, ast.Name):
            return None
        from .namespace import _fndefs
        if callsite.func.id not in _fndefs:
            return None
        candidate = _fndefs[callsite.func.id]

        # For now, only support simple positional arguments
        # and keyword arguments
        if callsite.starargs:
            return False
        if callsite.kwargs:
            return False
        if candidate.args.vararg:
            return False
        if candidate.args.kwonlyargs:
            return False
        if candidate.args.kw_defaults:
            return False
        if candidate.args.kwarg:
            return False
        if candidate.args.defaults:
            return False

        # Attempt to match up the calling convention at the callsite
        # with the candidate funcdef
        if 0:
            print(pretty_dump(callsite))
            print(pretty_dump(candidate))
        if len(callsite.args) > len(candidate.args.args):
            return None
        actual_pos_args = []
        try:
            slots = {}
            for idx, arg in enumerate(callsite.args):
                slots[idx] = arg
            for actual_kwarg in callsite.keywords:
                idx = locate_kwarg(candidate, actual_kwarg.arg)
                if idx in slots:
                    raise ValueError('positional slot %i already filled' % idx)
                slots[idx] = actual_kwarg.value
            for idx in range(len(candidate.args.args)):
                if idx not in slots:
                    raise ValueError('argument %i not filled' % idx)
                actual_pos_args.append(slots[idx])
        except ValueError:
            return None
        if 0:
            print(actual_pos_args)
        # For now, only allow functions that simply return a value
        body = candidate.body
        if len(body) != 1:
            return None
        if not isinstance(body[0], ast.Return):
            return None

        # Walk the candidate's nodes looking for potential problems
        c = Checker()
        c.visit(body[0])
        if c.problems:
            return None

        # All checks passed
        return Expansion(candidate, actual_pos_args)

    def visit_Call(self, node):
        if not self.config.inlining:
            return

        # TODO: renaming variables to avoid clashes
        # or do something like:
        #   .saved_locals = locals()
        #   set params to args
        #   body of called function
        #   locals() = .saved_locals
        #   how to things that aren't just a return
        #   how to handle early return
        # TODO: what guards are needed?
        # etc
        expansion = self.can_inline(node)
        if not expansion:
            return node
        funcdef = expansion.funcdef
        if 0:
            print(pretty_dump(funcdef))
        # Substitute the Call with the expression of the single return stmt
        # within the callee.
        # This assumes a single Return stmt
        returned_expr = funcdef.body[0].value
        # Rename params/args
        v = RenameVisitor(node, funcdef, expansion.actual_pos_args)
        new_expr = v.visit(returned_expr)
        return new_expr
