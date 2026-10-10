import os, shutil, subprocess, unittest
from test_app import Base


class TestCalculator(Base):
    def test_calculator_in_income_and_expense_dialogs_only(self):
        for url in ("/income/", "/expenses/"):
            h = self.c.get(url).get_data(as_text=True)
            self.assertEqual(h.count('class="calc"'), 1, url)
            self.assertIn("calc-toggle", h)
            self.assertIn("js/calc.js", h)
            self.assertEqual(h.count('name="amount"'), 1)  # the field is still a normal amount input
        self.assertNotIn('class="calc"', self.c.get("/accounts/").get_data(as_text=True))

    def test_calculator_does_not_break_saving(self):
        self.assertIn("Income added", self.income("12.50").get_data(as_text=True))

    @unittest.skipUnless(shutil.which("node"), "node not installed")
    def test_expression_evaluator(self):
        here = os.path.dirname(os.path.abspath(__file__))
        r = subprocess.run(["node", os.path.join(here, "calc_test.js")], capture_output=True, text=True)
        self.assertEqual(r.returncode, 0, r.stdout + r.stderr)


if __name__ == "__main__":
    unittest.main()
