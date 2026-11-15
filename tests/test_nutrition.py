import unittest

from pydantic import ValidationError

from food_log.nutrition import Assessment, Item, PhotoAssessment


def item(**changes):
    return Item(**(dict(name="Рис", portion_grams=300, eaten_fraction=0.5,
                       kcal=390, protein=9, fat=3, carbs=84) | changes))


class NutritionTests(unittest.TestCase):
    def test_new_photo_analysis_cannot_request_weights_or_other_clarifications(self):
        with self.assertRaises(ValidationError):
            PhotoAssessment(status="clarify", items=[], explanation="", question="Сколько грамм?")
        with self.assertRaises(ValidationError):
            PhotoAssessment(status="ok", items=[item()], explanation="", question="Сколько грамм?")

    def test_half_portion_is_counted_once(self):
        result = Assessment(status="ok", items=[item()], explanation="", question="")
        self.assertEqual(result.totals(), dict(kcal=195, protein=4.5, fat=1.5, carbs=42))

    def test_already_eaten_weight_is_not_halved_again(self):
        result = Assessment(status="ok", items=[item(portion_grams=150,
                            eaten_fraction=1, kcal=195)], explanation="", question="")
        self.assertEqual(result.totals()["kcal"], 195)

    def test_invalid_numbers_are_rejected(self):
        for change in ({"kcal": -1}, {"fat": float("nan")},
                       {"eaten_fraction": 1.1}, {"carbs": float("inf")}):
            with self.subTest(change=change), self.assertRaises(ValidationError):
                item(**change)

    def test_uncertain_or_nonfood_does_not_count(self):
        for status in ("clarify", "not_food"):
            result = Assessment(status=status, items=[], explanation="", question="Что за соус?")
            self.assertIsNone(result.totals())

    def test_ok_requires_food(self):
        with self.assertRaises(ValidationError):
            Assessment(status="ok", items=[], explanation="", question="")

    def test_glycemic_load_uses_reference_and_eaten_carbs(self):
        result = Assessment(status="ok", items=[item(gi_key="quinoa_cooked", available_carbs=40)],
                            explanation="", question="")
        value, incomplete = result.glycemic_load()
        self.assertAlmostEqual(value, 53 * 40 * .5 / 100)
        self.assertFalse(incomplete)

    def test_unknown_gi_is_not_zero(self):
        result = Assessment(status="ok", items=[item(gi_key=None, available_carbs=40)],
                            explanation="", question="")
        self.assertEqual(result.glycemic_load(), (None, True))

    def test_available_carbs_cannot_exceed_total(self):
        with self.assertRaises(ValidationError):
            item(available_carbs=100)
