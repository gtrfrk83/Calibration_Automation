"""The uncertainty calculator engine: statistics, Student t, ANOVA between-group component, Welch-Satterthwaite, rounding up, CMC and TUR."""
import math
import sys
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
import uncertainty_calc as uc


class Statistics(unittest.TestCase):
    def test_sample_standard_deviation_and_parse(self):
        v = uc.parse_readings('10.1, 10.2\n10.3;10.4\t10.5')
        self.assertEqual(v, [10.1, 10.2, 10.3, 10.4, 10.5])
        self.assertAlmostEqual(uc.stdev(v), math.sqrt(0.025), 12)
        with self.assertRaises(uc.CalcError):
            uc.parse_readings('1, abc')
        with self.assertRaises(uc.CalcError):
            uc.stdev([1.0])

    def test_student_t_matches_the_gum_table_g2_for_95_45_percent(self):
        gum = {1: 13.97, 2: 4.53, 3: 3.31, 4: 2.87, 5: 2.65, 10: 2.28, 20: 2.13, 30: 2.09, 50: 2.05, 100: 2.025}
        for dof, want in gum.items():
            self.assertAlmostEqual(uc.t_factor(dof), want, delta=0.011, msg=dof)
        self.assertEqual(uc.t_factor(uc.INF), 2.0)
        self.assertAlmostEqual(uc.t_factor(1e9), 2.0, places=3)


class TypeA(unittest.TestCase):
    def test_repeatability_u_is_s_over_root_m(self):
        v = [10.0, 10.2, 9.8, 10.1, 9.9]
        r = uc.repeatability(v)                          # averaged defaults to n
        s = uc.stdev(v)
        self.assertAlmostEqual(r.s, s, 12)
        self.assertAlmostEqual(r.u, s / math.sqrt(5), 12)
        self.assertEqual(r.dof, 4)
        r1 = uc.repeatability(v, averaged=1)
        self.assertAlmostEqual(r1.u, s, 12)

    def test_reproducibility_between_group_component_is_the_anova_one(self):
        groups = {'A': [10.0, 10.1, 9.9], 'B': [10.3, 10.4, 10.2], 'C': [10.1, 10.2, 10.0]}
        r = uc.reproducibility(groups)
        self.assertEqual((r.g, r.N, r.dof_between, r.dof_within), (3, 9, 2, 6))
        msw = 0.01                                        # each group has s = 0.1
        self.assertAlmostEqual(r.msw, msw, 12)
        means = [10.0, 10.3, 10.1]
        gm = sum(means) / 3
        msb = 3 * sum((m - gm) ** 2 for m in means) / 2
        self.assertAlmostEqual(r.msb, msb, 12)
        self.assertAlmostEqual(r.sigma_b, math.sqrt((msb - msw) / 3), 12)

    def test_no_between_group_spread_gives_zero_not_a_negative_root(self):
        r = uc.reproducibility({'A': [1.0, 2.0, 3.0], 'B': [1.0, 2.0, 3.0]})
        self.assertEqual(r.sigma_b, 0.0)

    def test_unequal_group_sizes_use_n0(self):
        r = uc.reproducibility({'A': [1.0, 1.2], 'B': [1.5, 1.6, 1.7, 1.8]})
        N = 6
        self.assertAlmostEqual(r.n0, (N - (4 + 16) / N) / 1, 12)

    def test_needs_two_groups(self):
        with self.assertRaises(uc.CalcError):
            uc.reproducibility({'A': [1.0, 2.0]})


class Budget(unittest.TestCase):
    def test_combination_divisors_and_welch_satterthwaite(self):
        rep = uc.repeatability([10.0, 10.2, 9.8, 10.1, 9.9], averaged=1)
        b = [uc.component('Standard', 0.4, 'k2'), uc.component('Resolution', 0.05, 'rect')]
        res = uc.budget(b, rep=rep, k_mode='auto')
        us = [rep.u, 0.4 / 2, 0.05 / math.sqrt(3)]
        uc_ = math.sqrt(sum(x * x for x in us))
        self.assertAlmostEqual(res.u_c, uc_, 12)
        veff = uc_ ** 4 / (rep.u ** 4 / 4)
        self.assertAlmostEqual(res.dof_eff, veff, 9)
        self.assertAlmostEqual(res.k, uc.t_factor(math.floor(veff)), 9)           # GUM G.4: dof_eff truncated down
        self.assertAlmostEqual(res.U, res.k * uc_, 12)
        self.assertGreaterEqual(res.reported, res.U)                 # rounded UP, never down
        self.assertAlmostEqual(sum(p for _c, p in res.shares()), 100.0, 9)

    def test_all_type_b_means_infinite_dof_and_k_2(self):
        res = uc.budget([uc.component('A', 1.0, 'k2'), uc.component('B', 1.0, 'std')])
        self.assertEqual((res.dof_eff, res.k), (uc.INF, 2.0))
        self.assertAlmostEqual(res.U, 2 * math.sqrt(0.25 + 1), 12)

    def test_fixed_k_and_sensitivity(self):
        res = uc.budget([uc.component('A', 2.0, 'std', sensitivity=-0.5)], k_mode='fixed', fixed_k=3)
        self.assertAlmostEqual(res.u_c, 1.0, 12)
        self.assertAlmostEqual(res.U, 3.0, 12)

    def test_cmc_floor_and_tur(self):
        res = uc.budget([uc.component('A', 0.001, 'std')], cmc=0.01, tolerance=0.1)
        self.assertEqual(res.reported, 0.01)
        self.assertIn('CMC', res.reported_note)
        self.assertAlmostEqual(res.tur, 10.0, 9)

    def test_ceil_sig_never_rounds_down(self):
        self.assertEqual(uc.ceil_sig(0.001231), 0.0013)
        self.assertEqual(uc.ceil_sig(0.0013), 0.0013)
        self.assertEqual(uc.ceil_sig(12.0), 12.0)

    def test_groups_only_uses_the_pooled_within_group_s_once(self):
        rpr = uc.reproducibility({'D1': [1.0, 1.1, 0.9], 'D2': [1.2, 1.3, 1.1]})
        res = uc.budget([], rpr=rpr)
        names = [c.name for c in res.components]
        self.assertEqual(names, ['Repeatability (Type A)', 'Reproducibility (Type A)'])
        self.assertTrue(any('pooled' in n for n in res.notes))

    def test_nothing_to_combine_and_bad_inputs(self):
        with self.assertRaises(uc.CalcError):
            uc.budget([])
        with self.assertRaises(uc.CalcError):
            uc.component('x', 'abc')
        with self.assertRaises(uc.CalcError):
            uc.component('x', 1, 'nope')


if __name__ == '__main__':
    unittest.main()
