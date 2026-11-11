"""Unit-тесты Retrieval V2: стемминг + нормализация «сим-карт*».

Проверяем, что нормализация применяется одинаково к индексу и запросу
и не разрушает числа, единицы и названия продуктов.
"""

import retrieval


def test_stem_inflections():
    # Падежи/числа одного слова дают общий стем.
    assert set(retrieval.tokenize("оператора")) & set(retrieval.tokenize("операторов"))
    assert set(retrieval.tokenize("счётчик")) & set(retrieval.tokenize("счётчиков"))
    assert set(retrieval.tokenize("магазина")) & set(retrieval.tokenize("магазинов"))


def test_stem_keeps_meaningful_words():
    # Короткие и неруские слова не стеммятся/не ломаются.
    toks = retrieval.tokenize("ASKUE 750 кВт")
    assert "750" in toks and "квт" in toks
    assert "askue" in toks


def test_units_and_numbers_preserved():
    toks = retrieval.tokenize("750 кВт и 750 000 кВт·ч, 1 МВт, 20 МВт")
    for t in ("750", "000", "квт", "ч", "1", "мвт", "20"):
        assert t in toks
    # «кВт·ч» не должно сливаться с «кВт» — это разные токены.
    assert "квтч" not in toks


def test_sim_family_unified():
    # Все формы «сим-карта» и разговорное «симки» дают общий токен.
    canonical = set(retrieval.tokenize("сим-картами"))
    for phrase in ("SIM", "sim", "симки", "сим-карта", "сим-карты",
                   "SIM-карты", "симкарта"):
        assert canonical & set(retrieval.tokenize(phrase)), phrase


def test_sim_does_not_eat_other_words():
    # «сим» само по себе и посторонние слова не превращаются в симкарта.
    assert "симкарта" not in retrieval.tokenize("сим")
    assert "симкарта" not in retrieval.tokenize("симптомы")
    assert "симкарта" not in retrieval.tokenize("посещение")


def test_product_names_stable():
    # Названия продуктов/разделов должны оставаться различимыми.
    toks = retrieval.tokenize("Орем АСКУЭ Потери Свет")
    for t in ("орем", "аскуэ", "потер", "свет"):
        assert t in toks
    # Разные продукты не сливаются в один токен.
    assert len(set(toks)) == len(toks)


def test_top_k_default_is_8(monkeypatch):
    monkeypatch.delenv("TOP_K", raising=False)
    assert retrieval._env_top_k() == 8
    monkeypatch.setenv("TOP_K", "5")
    assert retrieval._env_top_k() == 5
    monkeypatch.setenv("TOP_K", "99")
    assert retrieval._env_top_k() == 30  # верхняя граница сохранена
    monkeypatch.setenv("TOP_K", "bad")
    assert retrieval._env_top_k() == 8


def test_stem_does_not_destroy_short_words():
    # Слова <5 букв и некириллица не стеммятся.
    assert "кот" in retrieval.tokenize("кот")
    assert "abc" in retrieval.tokenize("abc")
