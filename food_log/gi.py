"""Малый проверяемый справочник; неизвестные ГИ не генерируются моделью."""

SOURCE = "https://glycemicindex.com/faqs/"
# University of Sydney, FAQ 29. Конкретный продукт, не среднее для всей категории.
CATALOG = {
    "red_lentils_cooked": {"name": "Красная чечевица, варёная", "gi": 26, "source": SOURCE},
    "cannellini_canned": {"name": "Фасоль каннеллини, консервированная, без жидкости", "gi": 31, "source": SOURCE},
    "baked_beans_canned": {"name": "Baked beans, консервированные в томатном соусе", "gi": 49, "source": SOURCE},
    "quinoa_cooked": {"name": "Киноа, варёная", "gi": 53, "source": SOURCE},
}
