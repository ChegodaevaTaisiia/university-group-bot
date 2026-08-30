from bot.services.homework_ai import fuzzy_same, normalize


def test_normalize_strips_punct_and_case():
    assert normalize("Задача №5, стр. 12!") == "задача 5 стр 12"


def test_fuzzy_same_true_for_paraphrase():
    a = "Прочитать параграф 3 и решить задачи 1-4"
    b = "решить задачи 1-4, прочитать параграф 3"
    assert fuzzy_same(a, b) is True


def test_fuzzy_same_false_for_different():
    a = "Прочитать параграф 3"
    b = "Сделать презентацию про Канта на 10 слайдов"
    assert fuzzy_same(a, b) is False
