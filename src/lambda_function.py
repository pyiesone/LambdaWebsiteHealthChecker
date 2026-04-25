import json
import logging
import os
import time
from datetime import datetime, timezone
from http.client import RemoteDisconnected
from typing import Iterable
from urllib import error, parse, request


LOGGER = logging.getLogger()
LOGGER.setLevel(logging.INFO)


TEXTMEBOT_ENDPOINT = "https://api.textmebot.com/send.php"
DEFAULT_TIMEOUT_SECONDS = 10
DEFAULT_EXPECTED_STATUS_CODES = {200}
TEXTMEBOT_DELAY_SECONDS = 5


def get_env(name: str, default: str | None = None, required: bool = False) -> str:
    value = os.getenv(name, default)
    if required and not value:
        raise ValueError(f"Missing required environment variable: {name}")
    return value or ""


def parse_expected_status_codes(raw_value: str | None) -> set[int]:
    if not raw_value:
        return set(DEFAULT_EXPECTED_STATUS_CODES)

    parsed = set()
    for item in raw_value.split(","):
        candidate = item.strip()
        if not candidate:
            continue
        parsed.add(int(candidate))

    if not parsed:
        raise ValueError("EXPECTED_STATUS_CODES must contain at least one HTTP status code")

    return parsed


def parse_recipients(raw_value: str | None) -> list[str]:
    if not raw_value:
        return []
    return [item.strip() for item in raw_value.split(",") if item.strip()]


def build_request(url: str) -> request.Request:
    return request.Request(
        url,
        headers={
            "User-Agent": get_env("USER_AGENT", "site-health-checker/1.0"),
            "Accept": "*/*",
        },
        method="GET",
    )


def check_website(url: str, timeout_seconds: int, expected_status_codes: Iterable[int]) -> tuple[bool, str]:
    expected = set(expected_status_codes)

    try:
        with request.urlopen(build_request(url), timeout=timeout_seconds) as response:
            status_code = response.getcode()
            if status_code in expected:
                return True, f"Website is healthy. HTTP {status_code}."
            return False, f"Website returned unexpected status code HTTP {status_code}."
    except error.HTTPError as exc:
        return False, f"Website returned HTTP {exc.code}."
    except error.URLError as exc:
        reason = getattr(exc, "reason", "unknown network error")
        return False, f"Website request failed: {reason}."
    except RemoteDisconnected:
        return False, "Website request failed: remote server closed the connection."
    except TimeoutError:
        return False, "Website request timed out."


def build_alert_message(target_url: str, health_message: str) -> str:
    timestamp = datetime.now(timezone.utc).isoformat(timespec="seconds")
    return f"[Website Down] {target_url} | {health_message} | checked_at={timestamp}"


def build_manual_test_message(custom_message: str | None = None) -> str:
    timestamp = datetime.now(timezone.utc).isoformat(timespec="seconds")
    if custom_message:
        return f"[TextMeBot Test] {custom_message} | triggered_at={timestamp}"
    return f"[TextMeBot Test] Manual Lambda invocation succeeded. triggered_at={timestamp}"


def send_textmebot_alert(recipient: str, api_key: str, message: str, timeout_seconds: int) -> dict:
    query = parse.urlencode(
        {
            "recipient": recipient,
            "apikey": api_key,
            "text": message,
        }
    )
    alert_url = f"{TEXTMEBOT_ENDPOINT}?{query}"

    try:
        with request.urlopen(alert_url, timeout=timeout_seconds) as response:
            body = response.read().decode("utf-8", errors="replace")
            return {
                "success": True,
                "status_code": response.getcode(),
                "body": body,
            }
    except error.HTTPError as exc:
        body = exc.read().decode("utf-8", errors="replace") if exc.fp else ""
        return {
            "success": False,
            "status_code": exc.code,
            "body": body,
            "error": f"TextMeBot returned HTTP {exc.code}.",
        }
    except error.URLError as exc:
        reason = getattr(exc, "reason", "unknown network error")
        return {
            "success": False,
            "status_code": None,
            "body": "",
            "error": f"TextMeBot request failed: {reason}.",
        }
    except RemoteDisconnected:
        return {
            "success": False,
            "status_code": None,
            "body": "",
            "error": "TextMeBot request failed: remote server closed the connection.",
        }
    except TimeoutError:
        return {
            "success": False,
            "status_code": None,
            "body": "",
            "error": "TextMeBot request timed out.",
        }


def send_textmebot_alerts(recipients: Iterable[str], api_key: str, message: str, timeout_seconds: int) -> list[dict]:
    recipients_list = list(recipients)
    results = []
    for index, recipient in enumerate(recipients_list):
        alert_result = send_textmebot_alert(recipient, api_key, message, timeout_seconds)
        results.append(
            {
                "recipient": recipient,
                "success": alert_result["success"],
                "status_code": alert_result["status_code"],
                "body": alert_result["body"],
                "error": alert_result.get("error"),
            }
        )
        if index < len(recipients_list) - 1:
            time.sleep(TEXTMEBOT_DELAY_SECONDS)
    return results


def get_notification_config() -> tuple[list[str], str, int]:
    recipients = parse_recipients(get_env("TEXTMEBOT_PHONES"))
    if not recipients:
        raise ValueError("Missing required environment variable: TEXTMEBOT_PHONES")
    api_key = get_env("TEXTMEBOT_API_KEY", required=True)
    timeout_seconds = int(get_env("REQUEST_TIMEOUT_SECONDS", str(DEFAULT_TIMEOUT_SECONDS)))
    return recipients, api_key, timeout_seconds


def lambda_handler(event, context):
    target_url = get_env("TARGET_URL", required=True)
    recipients, api_key, timeout_seconds = get_notification_config()
    expected_status_codes = parse_expected_status_codes(get_env("EXPECTED_STATUS_CODES"))

    is_healthy, health_message = check_website(target_url, timeout_seconds, expected_status_codes)

    result = {
        "target_url": target_url,
        "healthy": is_healthy,
        "message": health_message,
    }

    if is_healthy:
        LOGGER.info("Health check passed: %s", json.dumps(result))
        return {
            "statusCode": 200,
            "body": json.dumps(result),
        }

    alert_message = build_alert_message(target_url, health_message)
    alert_results = send_textmebot_alerts(recipients, api_key, alert_message, timeout_seconds)
    result["alerts"] = alert_results
    result["alert_failures"] = [item for item in alert_results if not item["success"]]

    LOGGER.warning("Health check failed and alert was sent: %s", json.dumps(result))
    return {
        "statusCode": 503,
        "body": json.dumps(result),
    }


def manual_test_handler(event, context):
    recipients, api_key, timeout_seconds = get_notification_config()
    custom_message = None
    if isinstance(event, dict):
        custom_message = event.get("message")

    test_message = build_manual_test_message(custom_message)
    alert_results = send_textmebot_alerts(recipients, api_key, test_message, timeout_seconds)
    failed_alerts = [item for item in alert_results if not item["success"]]
    result = {
        "healthy": not failed_alerts,
        "message": "Manual TextMeBot test message sent." if not failed_alerts else "Manual TextMeBot test encountered delivery failures.",
        "alerts": alert_results,
    }
    LOGGER.info("Manual TextMeBot test executed: %s", json.dumps(result))
    return {
        "statusCode": 200 if not failed_alerts else 502,
        "body": json.dumps(result),
    }
