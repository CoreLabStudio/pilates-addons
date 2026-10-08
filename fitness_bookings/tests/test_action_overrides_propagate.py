# -*- coding: utf-8 -*-
"""An action_* override must not throw away what super() returned.

Whatever an ``action_*`` method returns IS the next thing the user sees:
a dialog, a redirect, a reload. An override that calls ``super()`` and
discards the result silently deletes whatever the base wanted to show,
and the button does nothing at all.

That is not hypothetical. ``fitness_packages`` and
``fitness_notifications`` both did it to ``action_cancel``, so the
manager's "Cancel Booking (Late)" dialog never opened on any build since
the initial import - and because the base returns that action BEFORE
cancelling, the overrides then ran their post-cancellation work on a
booking that was never cancelled and sent the student a cancellation
email for a class she still had a place in.

No behaviour test can catch the NEXT one of these, because the next one
will be on a method nobody thought to test. So this reads the source.

It is parsed with ast rather than grepped, because a regex cannot tell a
``super()`` call whose value is used from one whose value is dropped, and
that distinction is the entire check.
"""
import ast
import io
import os

from odoo.tests import TransactionCase, tagged

#: Overrides allowed to drop the result, each with the reason. Empty, and
#: that is the point: an entry here is a decision somebody has to defend
#: in review, not a line that slips in unnoticed.
ALLOWED = {
    # 'module/models/thing.py:action_x': 'why it cannot propagate',
}


@tagged("post_install", "-at_install")
class TestActionOverridesPropagate(TransactionCase):

    longMessage = False

    @staticmethod
    def _addons_root():
        # .../fitness_bookings/tests/this_file.py -> the addons directory
        here = os.path.dirname(os.path.abspath(__file__))
        return os.path.dirname(os.path.dirname(here))

    @classmethod
    def _scan(cls, root=None):
        """[(path, method, line)] for every discarded super() result."""
        root = root or cls._addons_root()
        dropped = []
        for module in sorted(os.listdir(root)):
            if not module.startswith('fitness_'):
                continue
            mod_dir = os.path.join(root, module)
            if not os.path.isdir(mod_dir):
                continue
            for dirpath, _dirs, files in os.walk(mod_dir):
                if '__pycache__' in dirpath or os.sep + 'tests' in dirpath:
                    continue
                for name in files:
                    if not name.endswith('.py'):
                        continue
                    full = os.path.join(dirpath, name)
                    rel = os.path.relpath(full, root).replace('\\', '/')
                    try:
                        tree = ast.parse(
                            io.open(full, encoding='utf-8').read())
                    except SyntaxError:
                        continue
                    dropped.extend(cls._scan_tree(tree, rel))
        return dropped

    @staticmethod
    def _scan_tree(tree, rel):
        out = []
        for node in ast.walk(tree):
            if not isinstance(node, ast.FunctionDef):
                continue
            if not node.name.startswith('action_'):
                continue
            for stmt in ast.walk(node):
                # A discarded call is a bare expression statement.
                if not (isinstance(stmt, ast.Expr)
                        and isinstance(stmt.value, ast.Call)):
                    continue
                fn = stmt.value.func
                if not isinstance(fn, ast.Attribute):
                    continue
                inner = fn.value
                if (isinstance(inner, ast.Call)
                        and isinstance(inner.func, ast.Name)
                        and inner.func.id == 'super'):
                    out.append((rel, node.name, stmt.value.lineno))
        return out

    # == the check ====================================================
    def test_no_action_override_drops_the_super_result(self):
        dropped = self._scan()
        unexpected = [
            d for d in dropped
            if '%s:%s' % (d[0], d[1]) not in ALLOWED
        ]
        self.assertEqual(
            unexpected, [],
            "these action_* overrides call super() and throw the result "
            "away, so whatever the base wanted to show - a dialog, a "
            "redirect - never reaches the user:\n%s"
            % '\n'.join('    %s:%s  %s()' % (p, line, method)
                        for p, method, line in unexpected))

    def test_the_two_that_caused_this_still_propagate(self):
        """Named, so a revert of either is this test and not a mystery."""
        dropped = {'%s:%s' % (p, m) for p, m, _l in self._scan()}
        for path in (
            'fitness_packages/models/fitness_booking.py:action_cancel',
            'fitness_notifications/models/fitness_booking.py:action_cancel',
        ):
            self.assertNotIn(
                path, dropped,
                "%s has gone back to dropping super()'s result: the "
                "manager's late-cancel dialog will not open and students "
                "will be emailed about cancellations that did not happen"
                % path)

    # == the check can fail ===========================================
    def test_the_scan_detects_a_dropped_result(self):
        """A test that cannot fail is not a test.

        Without this, deleting the body of _scan_tree would leave both
        assertions above passing on an empty list for ever.
        """
        tree = ast.parse(
            "class A:\n"
            "    def action_thing(self):\n"
            "        super().action_thing()\n"
            "        return 1\n")
        self.assertEqual(
            [(p, m) for p, m, _l in self._scan_tree(tree, 'x.py')],
            [('x.py', 'action_thing')],
            "the scan does not notice a discarded super() result, so it "
            "would pass on any codebase at all")

    def test_the_scan_accepts_a_propagated_result(self):
        """And it must not fail the correct shape, or it would be
        switched off within a week."""
        for source in (
            "class A:\n"
            "    def action_thing(self):\n"
            "        return super().action_thing()\n",

            "class A:\n"
            "    def action_thing(self):\n"
            "        result = super().action_thing()\n"
            "        return result\n",
        ):
            self.assertEqual(
                self._scan_tree(ast.parse(source), 'x.py'), [],
                "the scan flags an override that does propagate, so it "
                "will be silenced rather than obeyed")

    def test_it_only_looks_at_action_methods(self):
        """A plain override dropping super()'s return is ordinary Python
        and not this defect; flagging it would bury the real ones."""
        tree = ast.parse(
            "class A:\n"
            "    def write(self, vals):\n"
            "        super().write(vals)\n")
        self.assertEqual(self._scan_tree(tree, 'x.py'), [])
