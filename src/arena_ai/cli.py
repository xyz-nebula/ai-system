"""Terminal client for exercising the public AI service API."""

import argparse
from uuid import uuid4

import httpx

from arena_ai.contracts import FinishResponse, SessionSnapshot, SessionState, TurnResponse

DEMO_CASE = {
    "id": "next-day",
    "title": "На следующий день...",
    "shared_context": (
        "Результативный Менеджер по продажам договорился с Генеральным директором о повышении "
        "зарплаты при выполнении KPI. На следующий день Менеджер не вышел на работу и сообщил "
        "об отравлении. Директор сомневается в его готовности к большей ответственности."
    ),
    "player_role": "Менеджер",
    "opponent_role": "Генеральный директор",
    "player_private_context": (
        "Сохранить договорённость о повышении и рабочие отношения. Готов компенсировать "
        "последствия пропуска. Максимальная уступка — один контрольный месяц с заранее "
        "согласованными KPI и автоматическим повышением после их выполнения."
    ),
    "opponent_private_context": (
        "Добиться подтверждения ответственности Менеджера. Начать с предложения контрольного "
        "месяца и KPI 130%; желательная сделка — две недели и KPI 120%. Не соглашаться "
        "на повышение раньше одной контрольной недели."
    ),
    "opponent_private_phrases": ["желательная сделка", "не соглашаться на повышение"],
    "agreement_rules": {
        "min_control_weeks": 1,
        "max_control_weeks": 4,
        "min_kpi_percent": 100,
        "max_kpi_percent": 130,
        "require_automatic_raise": True,
    },
}


def main() -> None:
    parser = argparse.ArgumentParser(description="Текстовый демо-клиент AI-контура")
    parser.add_argument("--api-url", default="http://127.0.0.1:8000")
    args = parser.parse_args()

    snapshot = SessionSnapshot(
        session_id=str(uuid4()), state=SessionState(turn_count=0), transcript=[]
    )
    print(f"Кейс: {DEMO_CASE['title']}")
    print(f"\nОбщие вводные: {DEMO_CASE['shared_context']}")
    print(f"\nВаша роль — {DEMO_CASE['player_role']}.")
    print(f"Ваши вводные: {DEMO_CASE['player_private_context']}")
    print(
        "\nСейчас оппонент работает в демонстрационном режиме без Qwen. "
        "Введите :history для истории, :finish для итога или :quit для выхода."
    )

    with httpx.Client(base_url=args.api_url, timeout=30.0) as client:
        while True:
            try:
                user_text = input("\nМенеджер > ").strip()
            except (EOFError, KeyboardInterrupt):
                print()
                break
            if user_text == ":quit":
                break
            if user_text == ":finish":
                try:
                    response = client.post(
                        "/v1/finish",
                        json={"case": DEMO_CASE, "snapshot": snapshot.model_dump(mode="json")},
                    )
                    response.raise_for_status()
                    finished = FinishResponse.model_validate(response.json())
                except (httpx.HTTPError, ValueError):
                    print("Не удалось получить итог поединка.")
                    continue
                outcome = finished.outcome
                print(f"Исход ({outcome.kind}): {outcome.summary}")
                if outcome.agreement is not None:
                    terms = outcome.agreement
                    print(
                        "  Условия: "
                        f"{terms.control_weeks} нед. контроля, KPI {terms.kpi_percent}%, "
                        f"автоматическое повышение: {'да' if terms.automatic_raise else 'нет'}"
                    )
                for commitment in outcome.commitments:
                    print(f"  Обязательство: {commitment}")
                for point in outcome.open_points:
                    print(f"  Открытый вопрос: {point}")
                if outcome.next_step:
                    print(f"  Следующий шаг: {outcome.next_step}")
                if outcome.reason:
                    print(f"  Причина: {outcome.reason}")
                judge_names = {
                    "hiring": "Нанимающиеся на работу",
                    "negotiation": "Отправляющие на переговоры",
                    "ownership": "Доверяющие собственность",
                }
                print("Демонстрационные судейские вердикты:")
                for slot in finished.judge_verdicts:
                    print(f"  {judge_names[slot.college]}:")
                    if slot.verdict is None:
                        print(f"    Вердикт отсутствует ({slot.error_code}).")
                        continue
                    verdict = slot.verdict
                    choice = "Менеджер" if verdict.choice == "player" else "Директор"
                    print(f"    Выбор: {choice}")
                    print(
                        f"    Наблюдение ({verdict.evidence_turn_id}): "
                        f"«{verdict.evidence_quote}» — {verdict.observation}"
                    )
                    print(f"    Эффект: {verdict.effect}")
                    print(f"    Сравнение: {verdict.comparison}")
                print("Демонстрационный тренерский разбор:")
                coach = finished.trainer_feedback
                if coach.feedback is None:
                    print(f"  Разбор отсутствует ({coach.error_code}).")
                else:
                    feedback = coach.feedback
                    print(f"  {feedback.summary}")
                    for label, points in (
                        ("Сильный момент", feedback.strengths),
                        ("Ошибка", feedback.mistakes),
                    ):
                        for point in points:
                            print(
                                f"  {label} ({point.evidence_turn_id}): "
                                f"«{point.evidence_quote}» — {point.action}"
                            )
                            print(f"    Изменение: {point.situation_change}")
                            print(f"    Последствие: {point.consequence}")
                    for recommendation in feedback.next_try:
                        print(f"  Следующая попытка: {recommendation}")
                break
            if user_text == ":history":
                if not snapshot.transcript:
                    print("История пока пуста.")
                for entry in snapshot.transcript:
                    speaker = "Менеджер" if entry.speaker == "player" else "Директор"
                    print(f"{speaker} [{entry.status}]: {entry.text}")
                print(f"Ходов: {snapshot.state.turn_count}")
                continue
            if not user_text:
                continue

            try:
                response = client.post(
                    "/v1/turn",
                    json={
                        "case": DEMO_CASE,
                        "snapshot": snapshot.model_dump(mode="json"),
                        "turn_id": str(uuid4()),
                        "user_text": user_text,
                    },
                )
                response.raise_for_status()
                result = TurnResponse.model_validate(response.json())
            except httpx.HTTPError as error:
                print(f"Сервис недоступен или отклонил ход: {type(error).__name__}")
                continue
            except ValueError:
                print("Сервис вернул некорректный ответ.")
                continue

            snapshot = result.snapshot
            if result.status == "model_error":
                print(f"Ход не принят ({result.error_code}): {result.opponent_text}")
                continue
            if result.status == "blocked":
                print("Ход заблокирован Guard.")
            print(f"Директор > {result.opponent_text}")
            print(f"Ходов: {snapshot.state.turn_count}")
            if snapshot.state.agreement is not None:
                terms = snapshot.state.agreement
                print(
                    "Договорённость: "
                    f"{terms.control_weeks} нед. контроля, KPI {terms.kpi_percent}%, "
                    f"автоматическое повышение: {'да' if terms.automatic_raise else 'нет'}"
                )
