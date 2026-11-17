from typing import Annotated, Literal

from pydantic import BaseModel, ConfigDict, Field, model_validator

Amount = Annotated[float, Field(ge=0, le=100000, allow_inf_nan=False)]


class Item(BaseModel):
    model_config = ConfigDict(extra="forbid")
    name: str
    portion_grams: Amount
    eaten_fraction: Annotated[float, Field(ge=0, le=1, allow_inf_nan=False)]
    # Пищевая ценность всей указанной порции, до применения eaten_fraction.
    kcal: Amount
    protein: Amount
    fat: Amount
    carbs: Amount

    @model_validator(mode="before")
    @classmethod
    def read_legacy_fields(cls, value):
        # Старые оценки в JSON остаются читаемыми; новая схема не содержит ГИ/ГН.
        if isinstance(value, dict):
            return {key: item for key, item in value.items()
                    if key not in ("gi_key", "available_carbs")}
        return value


class Assessment(BaseModel):
    model_config = ConfigDict(extra="forbid")
    status: Literal["ok", "clarify", "not_food"]
    items: list[Item]
    explanation: str
    question: str
    category: Literal["Завтрак", "Обед", "Ужин", "Полдник", "Перекус", "Без категории"] = "Без категории"

    @model_validator(mode="after")
    def check_status(self):
        if self.status == "ok" and not self.items:
            raise ValueError("Для оценки нужны продукты")
        if self.status == "clarify" and not self.question.strip():
            raise ValueError("Нужен вопрос для уточнения")
        if self.status != "ok" and self.items:
            raise ValueError("Неподтверждённые продукты не должны иметь оценку")
        return self

    def totals(self):
        if self.status != "ok":
            return None
        return {key: sum(getattr(item, key) * item.eaten_fraction for item in self.items)
                for key in ("kcal", "protein", "fat", "carbs")}

    def render(self):
        if self.status == "clarify":
            return ("Нужно уточнение; эта версия приёма пищи пока не учтена.\n"
                    + self.question[:1000] + "\nОтветь на это сообщение.")
        if self.status == "not_food":
            return "Не удалось определить еду. Запись не учтена.\n" + self.explanation[:1000]
        lines = [f"{self.category} · приблизительная оценка:"]
        for item in self.items[:20]:
            lines.append(f"• {item.name[:100]}: ≈{item.portion_grams * item.eaten_fraction:.0f} г")
        lines.append(format_totals(self.totals()))
        lines.append(self.explanation[:1200])
        lines.append("Учтено. Для исправления ответь на это сообщение.")
        return "\n".join(lines)


class PhotoAssessment(Assessment):
    # Старые clarify остаются читаемыми в базе, но модель их больше не возвращает.
    status: Literal["ok", "not_food"]
    question: Literal[""] = ""


def format_totals(values):
    return (f"{values['kcal']:.0f} ккал · Б {values['protein']:.1f} г · "
            f"Ж {values['fat']:.1f} г · У {values['carbs']:.1f} г")
