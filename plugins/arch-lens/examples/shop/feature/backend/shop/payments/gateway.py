import requests

PAYMENT_GATEWAY_URL = "https://payments.example.com/v1"


def charge(amount: int, currency: str, source: str) -> str:
    response = requests.post(
        f"{PAYMENT_GATEWAY_URL}/charges",
        json={"amount": amount, "currency": currency, "source": source},
    )
    return response.json()["id"]


def refund(charge_id: str, amount: int, reason: str) -> str:
    response = requests.post(
        f"{PAYMENT_GATEWAY_URL}/refunds",
        json={"charge": charge_id, "amount": amount, "reason": reason},
    )
    return response.json()["id"]
