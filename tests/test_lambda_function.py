import json
import os
import unittest
from http.client import RemoteDisconnected
from unittest.mock import Mock, patch
from urllib.error import HTTPError, URLError

from src import lambda_function


class ParseExpectedStatusCodesTests(unittest.TestCase):
    def test_defaults_to_200(self):
        self.assertEqual(lambda_function.parse_expected_status_codes(None), {200})

    def test_parses_comma_separated_list(self):
        self.assertEqual(lambda_function.parse_expected_status_codes("200, 204,301"), {200, 204, 301})


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
    @patch("src.lambda_function.send_textmebot_alert")
    @patch("src.lambda_function.check_website")
    def test_returns_200_without_alert_when_healthy(self, mock_check_website, mock_send_textmebot_alert):
        mock_check_website.return_value = (True, "Website is healthy. HTTP 200.")
        os.environ["TARGET_URL"] = "https://example.com/"
        os.environ["TEXTMEBOT_PHONE"] = "+10000000000"
        os.environ["TEXTMEBOT_API_KEY"] = "secret"

        response = lambda_function.lambda_handler({}, {})

        self.assertEqual(response["statusCode"], 200)
        self.assertFalse(mock_send_textmebot_alert.called)
        self.assertTrue(json.loads(response["body"])["healthy"])

    @patch("src.lambda_function.send_textmebot_alert")
    @patch("src.lambda_function.check_website")
    def test_returns_503_and_alert_payload_when_unhealthy(self, mock_check_website, mock_send_textmebot_alert):
        mock_check_website.return_value = (False, "Website returned HTTP 503.")
        mock_send_textmebot_alert.return_value = {"status_code": 200, "body": "ok"}
        os.environ["TARGET_URL"] = "https://example.com/"
        os.environ["TEXTMEBOT_PHONE"] = "+10000000000"
        os.environ["TEXTMEBOT_API_KEY"] = "secret"

        response = lambda_function.lambda_handler({}, {})

        self.assertEqual(response["statusCode"], 503)
        self.assertTrue(mock_send_textmebot_alert.called)
        self.assertEqual(json.loads(response["body"])["alert"]["status_code"], 200)

    @patch("src.lambda_function.send_textmebot_alert")
    def test_manual_test_handler_sends_message(self, mock_send_textmebot_alert):
        mock_send_textmebot_alert.return_value = {"status_code": 200, "body": "ok"}
        os.environ["TEXTMEBOT_PHONE"] = "+10000000000"
        os.environ["TEXTMEBOT_API_KEY"] = "secret"

        response = lambda_function.manual_test_handler({"message": "ping from console"}, {})

        self.assertEqual(response["statusCode"], 200)
        self.assertTrue(mock_send_textmebot_alert.called)
        payload = json.loads(response["body"])
        self.assertEqual(payload["alert"]["status_code"], 200)
        self.assertEqual(payload["message"], "Manual TextMeBot test message sent.")


if __name__ == "__main__":
    unittest.main()
