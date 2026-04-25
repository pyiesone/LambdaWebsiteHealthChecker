# Website Health Checker Lambda

This project deploys one AWS Lambda function that checks a website on a schedule and another Lambda function that you can invoke manually to verify TextMeBot WhatsApp delivery.

## What is included

- `src/lambda_function.py`: includes both the scheduled health-check handler and the manual TextMeBot test handler.
- `tests/test_lambda_function.py`: a small unit test suite.
- `.github/workflows/deploy.yml`: GitHub Actions workflow that deploys both Lambda functions and configures an EventBridge schedule for the health checker.

## How it works

1. EventBridge invokes the Lambda function on a schedule.
2. The Lambda function sends an HTTP GET request to the URL defined in the GitHub repository variable `TARGET_URL`.
3. If the site returns an unexpected status code or the request fails, the function calls TextMeBot's API to send a WhatsApp message to each phone number listed in the GitHub repository variable `TEXTMEBOT_PHONES`.
4. When multiple recipients are configured, the function sends the first TextMeBot request immediately, waits 10 seconds, then sends the next request.

The manual test Lambda sends WhatsApp test messages when you invoke it from the AWS console and returns delivery details for each recipient.

## GitHub repository setup

Create a GitHub repository from this folder, then add these repository secrets:

- `AWS_ROLE_TO_ASSUME`: IAM role ARN that GitHub Actions will assume through OIDC.
- `AWS_ACCOUNT_ID`: your AWS account ID.
- `LAMBDA_EXECUTION_ROLE_ARN`: IAM role ARN used by the Lambda function itself.
- `TEXTMEBOT_API_KEY`: your TextMeBot API key.

Add these repository variables:

- `TARGET_URL`: required. The website URL to check, for example `https://example.com/`.
- `TEXTMEBOT_PHONES`: required. A comma-separated list of WhatsApp numbers in the format expected by TextMeBot.
- `AWS_REGION`: defaults to `us-east-1`.
- `LAMBDA_FUNCTION_NAME`: defaults to `website-health-checker`.
- `MANUAL_TEST_LAMBDA_FUNCTION_NAME`: defaults to `website-health-checker-manual-test`.
- `LAMBDA_SCHEDULE_EXPRESSION`: defaults to `rate(5 minutes)`.
- `REQUEST_TIMEOUT_SECONDS`: defaults to `10`.
- `EXPECTED_STATUS_CODES`: defaults to `200`.

## AWS IAM requirements

### 1. GitHub Actions deployment role

This IAM role should trust GitHub's OIDC provider and allow at least:

- `lambda:GetFunctionConfiguration`
- `lambda:CreateFunction`
- `lambda:UpdateFunctionCode`
- `lambda:UpdateFunctionConfiguration`
- `lambda:PublishVersion`
- `lambda:AddPermission`
- `events:PutRule`
- `events:PutTargets`
- `iam:PassRole`

### 2. Lambda execution role

Attach at least the managed policy `AWSLambdaBasicExecutionRole` so the function can write logs to CloudWatch.

## Deploy

Push to `main` or trigger the `Deploy AWS Lambda` workflow manually.

By default, the EventBridge schedule runs every 5 minutes.

## Manual TextMeBot test

After deployment, open the Lambda function named by `MANUAL_TEST_LAMBDA_FUNCTION_NAME` in the AWS console and use the `Test` button to invoke it manually.

You can use an empty test event:

```json
{}
```

Or send a custom WhatsApp message:

```json
{
  "message": "TextMeBot manual test from AWS console"
}
```

The manual test Lambda uses the same `TEXTMEBOT_PHONES` variable and `TEXTMEBOT_API_KEY` secret as the health checker. If the invocation succeeds, every listed recipient should receive a WhatsApp message.

If TextMeBot rejects a request, the Lambda response includes per-recipient delivery results instead of failing with an uncaught exception. The manual test Lambda returns HTTP `502` when one or more TextMeBot deliveries fail.

## Notes

- The current implementation sends an alert on every failing invocation. If you want alert suppression or recovery notifications, add persistent state with DynamoDB or SSM Parameter Store.
- Store recipients only in the GitHub repository variable `TEXTMEBOT_PHONES`, for example `+10000000000,+20000000000`.
- With multiple recipients, TextMeBot requests are sent sequentially with a 10-second delay between recipients.
- TextMeBot's documented text message endpoint is `https://api.textmebot.com/send.php?recipient=[phone number]&apikey=[your apikey]&text=[text to send]`.
