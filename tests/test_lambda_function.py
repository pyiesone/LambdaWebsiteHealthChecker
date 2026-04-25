import json
import os
import unittest
from io import BytesIO
from http.client import RemoteDisconnected
from unittest.mock import Mock, patch
from urllib.error import HTTPError, URLError

from src import lambda_function


class ParseExpectedStatusCodesTests(unittest.TestCase):
    def test_defaults_to_200(self):
        self.assertEqual(lambda_function.parse_expected_status_codes(None), {200})

    def test_parses_comma_separated_list(self):
        self.assertEqual(lambda_function.parse_expected_status_codes("200, 204,301"), {200, 204, 301})

    def test_parses_comma_separated_recipients(self):
        self.assertEqual(
            lambda_function.parse_recipients("+10000000000, +20000000000"),
            ["+10000000000", "+20000000000"],
        )


class CheckWebsiteTests(unittest.TestCase):
    @patch("src.lambda_function.request.urlopen")
    def test_returns_healthy_when_status_matches(self, mock_urlopen):
        response = Mock()
        response.getcode.return_value = 200
        mock_urlopen.return_value.__enter__.return_value = response

        healthy, message = lambda_function.check_website("https://example.com", 5, {200})

        self.assertTrue(healthy)
        self.assertIn("HTTP 200", message)

    @patch("src.lambda_function.request.urlopen")
    def test_returns_unhealthy_on_http_error(self, mock_urlopen):
        mock_urlopen.side_effect = HTTPError(
            url="https://example.com",
            code=503,
            msg="Service Unavailable",
            hdrs=None,
            fp=None,
        )

        healthy, message = lambda_function.check_website("https://example.com", 5, {200})

        self.assertFalse(healthy)
        self.assertEqual(message, "Website returned HTTP 503.")

    @patch("src.lambda_function.request.urlopen")
    def test_returns_unhealthy_on_url_error(self, mock_urlopen):
        mock_urlopen.side_effect = URLError("dns failure")

        healthy, message = lambda_function.check_website("https://example.com", 5, {200})

        self.assertFalse(healthy)
        self.assertIn("dns failure", message)

    @patch("src.lambda_function.request.urlopen")
    def test_returns_unhealthy_on_remote_disconnect(self, mock_urlopen):
        mock_urlopen.side_effect = RemoteDisconnected("Remote end closed connection without response")

        healthy, message = lambda_function.check_website("https://example.com", 5, {200})

        self.assertFalse(healthy)
        self.assertEqual(message, "Website request failed: remote server closed the connection.")


class LambdaHandlerTests(unittest.TestCase):
    @patch("src.lambda_function.time.sleep")
    @patch("src.lambda_function.send_textmebot_alert")
    def test_send_textmebot_alerts_waits_between_recipients(self, mock_send_textmebot_alert, mock_sleep):
        mock_send_textmebot_alert.return_value = {"success": True, "status_code": 200, "body": "ok"}

        results = lambda_function.send_textmebot_alerts(
            ["+10000000000", "+20000000000"],
            "secret",
            "test",
            5,
        )

        self.assertEqual(len(results), 2)
        self.assertEqual(mock_send_textmebot_alert.call_count, 2)
        mock_sleep.assert_called_once_with(10)

    @patch("src.lambda_function.request.urlopen")
    def test_send_textmebot_alert_returns_failure_on_http_error(self, mock_urlopen):
        mock_urlopen.side_effect = HTTPError(
            url="https://api.textmebot.com/send.php",
            code=403,
            msg="Forbidden",
            hdrs=None,
            fp=BytesIO(b"forbidden"),
        )

        result = lambda_function.send_textmebot_alert("+10000000000", "secret", "test", 5)

        self.assertFalse(result["success"])
        self.assertEqual(result["status_code"], 403)
        self.assertEqual(result["error"], "TextMeBot returned HTTP 403.")

    @patch("src.lambda_function.send_textmebot_alerts")
    @patch("src.lambda_function.check_website")
    def test_returns_200_without_alert_when_healthy(self, mock_check_website, mock_send_textmebot_alerts):
        mock_check_website.return_value = (True, "Website is healthy. HTTP 200.")
        os.environ["TARGET_URL"] = "https://example.com/"
        os.environ["TEXTMEBOT_PHONES"] = "+10000000000,+20000000000"
        os.environ["TEXTMEBOT_API_KEY"] = "secret"

        response = lambda_function.lambda_handler({}, {})

        self.assertEqual(response["statusCode"], 200)
        self.assertFalse(mock_send_textmebot_alerts.called)
        self.assertTrue(json.loads(response["body"])["healthy"])

    @patch("src.lambda_function.send_textmebot_alerts")
    @patch("src.lambda_function.check_website")
    def test_returns_503_and_alert_payload_when_unhealthy(self, mock_check_website, mock_send_textmebot_alerts):
        mock_check_website.return_value = (False, "Website returned HTTP 503.")
        mock_send_textmebot_alerts.return_value = [
            {"recipient": "+10000000000", "success": True, "status_code": 200, "body": "ok", "error": None},
            {"recipient": "+20000000000", "success": True, "status_code": 200, "body": "ok", "error": None},
        ]
        os.environ["TARGET_URL"] = "https://example.com/"
        os.environ["TEXTMEBOT_PHONES"] = "+10000000000,+20000000000"
        os.environ["TEXTMEBOT_API_KEY"] = "secret"

        response = lambda_function.lambda_handler({}, {})

        self.assertEqual(response["statusCode"], 503)
        self.assertTrue(mock_send_textmebot_alerts.called)
        self.assertEqual(json.loads(response["body"])["alerts"][0]["status_code"], 200)

    @patch("src.lambda_function.send_textmebot_alerts")
    def test_manual_test_handler_sends_message(self, mock_send_textmebot_alerts):
        mock_send_textmebot_alerts.return_value = [{"recipient": "+10000000000", "success": True, "status_code": 200, "body": "ok", "error": None}]
        os.environ["TEXTMEBOT_PHONES"] = "+10000000000"
        os.environ["TEXTMEBOT_API_KEY"] = "secret"

        response = lambda_function.manual_test_handler({"message": "ping from console"}, {})

        self.assertEqual(response["statusCode"], 200)
        self.assertTrue(mock_send_textmebot_alerts.called)
        payload = json.loads(response["body"])
        self.assertEqual(payload["alerts"][0]["status_code"], 200)
        self.assertEqual(payload["message"], "Manual TextMeBot test message sent.")

    @patch("src.lambda_function.send_textmebot_alerts")
    def test_manual_test_handler_returns_502_when_delivery_fails(self, mock_send_textmebot_alerts):
        mock_send_textmebot_alerts.return_value = [
            {"recipient": "+10000000000", "success": False, "status_code": 403, "body": "forbidden", "error": "TextMeBot returned HTTP 403."}
        ]
        os.environ["TEXTMEBOT_PHONES"] = "+10000000000"
        os.environ["TEXTMEBOT_API_KEY"] = "secret"

        response = lambda_function.manual_test_handler({}, {})

        self.assertEqual(response["statusCode"], 502)
        payload = json.loads(response["body"])
        self.assertFalse(payload["healthy"])
        self.assertEqual(payload["alerts"][0]["status_code"], 403)


if __name__ == "__main__":
    unittest.main()
