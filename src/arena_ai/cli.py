"""Terminal client for exercising the public AI service API."""

import argparse
from uuid import uuid4

import httpx

DEMO_SCENARIO = {
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
}


def main() -> None:
    parser = argparse.ArgumentParser(description="Текстовый демо-клиент AI-контура")
    parser.add_argument("--api-url", default="http://127.0.0.1:8000")
    args = parser.parse_args()

    snapshot = {
        "session_id": str(uuid4()),
        "state": {"turn_count": 0},
        "transcript": [],
    }
    print(f"Кейс: {DEMO_SCENARIO['title']}")
    print(f"\nОбщие вводные: {DEMO_SCENARIO['shared_context']}")
    print(f"\nВаша роль — {DEMO_SCENARIO['player_role']}.")
    print(f"Ваши вводные: {DEMO_SCENARIO['player_private_context']}")
    print(
        "\nСейчас оппонент работает в демонстрационном режиме без Qwen. Введите :quit для выхода."
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
            if not user_text:
                continue

            try:
                response = client.post(
                    "/v1/turn",
                    json={
                        "scenario": DEMO_SCENARIO,
                        "snapshot": snapshot,
                        "turn_id": str(uuid4()),
                        "user_text": user_text,
                    },
                )
                response.raise_for_status()
                result = response.json()
            except httpx.HTTPError as error:
                print(f"Сервис недоступен или отклонил ход: {type(error).__name__}")
                continue
            except ValueError:
                print("Сервис вернул некорректный ответ.")
                continue

            snapshot = result["snapshot"]
            print(f"Директор > {result['opponent_text']}")
            print(f"Ходов: {snapshot['state']['turn_count']}")
