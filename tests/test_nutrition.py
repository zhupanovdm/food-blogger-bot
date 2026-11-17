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

    def test_schema_and_new_results_do_not_include_glycemic_fields(self):
        schema = PhotoAssessment.model_json_schema()
        self.assertNotIn("gi_key", str(schema))
        self.assertNotIn("available_carbs", str(schema))
        self.assertEqual(set(item().model_dump()),
                         {"name", "portion_grams", "eaten_fraction", "kcal", "protein", "fat", "carbs"})

    def test_legacy_glycemic_fields_remain_readable_and_are_not_resaved(self):
        import json
        saved = dict(status="ok", items=[dict(item().model_dump(),
                     gi_key="quinoa_cooked", available_carbs=40)], explanation="", question="")
        result = Assessment.model_validate_json(json.dumps(saved))
        self.assertEqual(result.totals()["kcal"], 195)
        self.assertNotIn("gi_key", result.model_dump_json())
        self.assertNotIn("available_carbs", result.model_dump_json())
        with self.assertRaises(ValidationError):
            item(unrecognized_field=1)
