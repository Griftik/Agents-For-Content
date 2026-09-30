from bot.services.insights import pick


def test_first_rule_with_list_condition(content):
    a = {"pain": "projects_not_done", "strategy_state": "in_my_head", "tried": "diy_session"}
    first, second = pick(a, content.insights)
    assert first.startswith("Проекты не доходят до реализации")
    assert second.startswith("Сессия своими силами")


def test_order_matters(content):
    # стратегия есть → первое правило не подходит, срабатывает второе для projects_not_done
    a = {"pain": "projects_not_done", "strategy_state": "team_knows", "tried": "nothing", "decisions": "alone"}
    first, second = pick(a, content.insights)
    assert first.startswith("Цель известна")
    assert second.startswith("Когда решения принимает один человек")


def test_default(content):
    a = {"pain": "unknown_code", "tried": "nothing", "decisions": "regular_top_meetings",
         "strategy_state": "team_knows", "outcome_6m": "clear_plan"}
    first, second = pick(a, content.insights)
    assert first == content.insights["default"]["first"].strip()
    assert second == content.insights["default"]["second"].strip()
