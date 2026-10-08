"""Gmail operations: label lookup/creation, metadata fetch, label add with retries."""

import json
import time

from googleapiclient.http import BatchHttpRequest

from .rules import RULE_PRIORITY


GMAIL_LABEL_WRITE_MAX_ATTEMPTS = 4
GMAIL_LABEL_WRITE_RETRY_DELAYS_SECONDS = (1, 2, 4)
BATCH_SIZE = 10
METADATA_RETRY_ATTEMPTS = 3
# Gmail rate limits are per minute, so retries must wait longer than a second.
RETRY_DELAYS_SECONDS = (5, 20)
BATCH_PAUSE_SECONDS = 0.5
REQUEST_MAX_ATTEMPTS = 4
REQUEST_RETRY_DELAYS_SECONDS = (2, 8, 30)
TRANSIENT_GMAIL_HTTP_STATUSES = {429, 500, 502, 503, 504}
TRANSIENT_GMAIL_403_REASONS = {
    "ratelimitexceeded",
    "userratelimitexceeded",
}


def gmail_http_status(error):
    """Return an HTTP status when a Gmail client error exposes one."""
    response = getattr(error, "resp", None)
    status = getattr(response, "status", None)
    if status is None:
        status = getattr(error, "status_code", None)
    if status is None:
        status = getattr(error, "code", None)
    try:
        return int(status)
    except (TypeError, ValueError):
        return None


def _structured_error_values(error):
    values = []
    content = getattr(error, "content", None)
    if isinstance(content, bytes):
        content = content.decode("utf-8", errors="replace")
    if isinstance(content, str):
        try:
            values.append(json.loads(content))
        except (TypeError, ValueError, json.JSONDecodeError):
            pass
    elif isinstance(content, (dict, list)):
        values.append(content)

    details = getattr(error, "error_details", None)
    if isinstance(details, (dict, list)):
        values.append(details)
    return values


def _reason_values(value):
    if isinstance(value, dict):
        for key, nested in value.items():
            if key.casefold() == "reason" and isinstance(nested, str):
                yield nested
            else:
                yield from _reason_values(nested)
    elif isinstance(value, list):
        for nested in value:
            yield from _reason_values(nested)


def gmail_error_reasons(error):
    """Extract structured Google API reason codes without string matching."""
    return {
        reason.casefold()
        for value in _structured_error_values(error)
        for reason in _reason_values(value)
    }


def is_retriable_gmail_error(error):
    """Identify transient Gmail failures, including narrow quota-related 403s."""
    status = gmail_http_status(error)
    if status in TRANSIENT_GMAIL_HTTP_STATUSES:
        return True
    return status == 403 and bool(
        gmail_error_reasons(error).intersection(TRANSIENT_GMAIL_403_REASONS)
    )


def add_gmail_label_with_retries(service, message_id, gmail_label_id, *, sleep=None):
    """Add one label with bounded retries while preserving the chosen label."""
    sleeper = sleep or time.sleep
    for attempt in range(GMAIL_LABEL_WRITE_MAX_ATTEMPTS):
        try:
            return service.users().messages().modify(
                userId="me",
                id=message_id,
                body={"addLabelIds": [gmail_label_id]},
            ).execute()
        except Exception as error:
            final_attempt = attempt == GMAIL_LABEL_WRITE_MAX_ATTEMPTS - 1
            if final_attempt or not is_retriable_gmail_error(error):
                raise
            sleeper(GMAIL_LABEL_WRITE_RETRY_DELAYS_SECONDS[attempt])


def execute_with_retries(request, *, sleep=None):
    """Run a Gmail request, retrying transient and per-minute rate-limit errors."""
    sleeper = sleep or time.sleep
    for attempt in range(REQUEST_MAX_ATTEMPTS):
        try:
            return request.execute()
        except Exception as error:
            final_attempt = attempt == REQUEST_MAX_ATTEMPTS - 1
            if final_attempt or not is_retriable_gmail_error(error):
                raise
            sleeper(REQUEST_RETRY_DELAYS_SECONDS[attempt])


def list_labels_by_name(service):
    response = execute_with_retries(service.users().labels().list(userId="me"))
    return {label["name"]: label for label in response.get("labels", [])}


def ensure_project_labels(service, label_names=RULE_PRIORITY):
    existing_labels = list_labels_by_name(service)
    already_existed = []
    created = []

    for label_name in label_names:
        if label_name in existing_labels:
            already_existed.append(label_name)
            continue

        execute_with_retries(
            service.users().labels().create(userId="me", body={"name": label_name})
        )
        created.append(label_name)

    return already_existed, created


def get_header(headers, name):
    return next(
        (header["value"] for header in headers if header["name"].lower() == name.lower()),
        "",
    )


def _metadata_request(service, message_id):
    return service.users().messages().get(
        userId="me",
        id=message_id,
        format="metadata",
        metadataHeaders=["From", "Subject"],
    )


def get_message_metadata(service, messages, batch_size=BATCH_SIZE, *, allow_partial=False):
    """Fetch message metadata in order, retrying only transient Gmail failures.

    The initial attempt is batched. A failed message gets at most two direct
    retries, so each message has at most ``METADATA_RETRY_ATTEMPTS`` total
    attempts. Callers that opt into partial results receive successful messages
    and per-message failures; existing callers retain all-or-nothing behavior.
    """
    responses = {}
    errors = {}

    def handle_response(message_id, response, exception):
        if exception is not None:
            errors[message_id] = exception
        else:
            responses[message_id] = response

    batch_uri = f"{service._baseUrl}{service._rootDesc['batchPath']}"
    for start in range(0, len(messages), batch_size):
        batch = BatchHttpRequest(callback=handle_response, batch_uri=batch_uri)
        for message in messages[start : start + batch_size]:
            message_id = message["id"]
            batch.add(
                _metadata_request(service, message_id),
                request_id=message_id,
            )
        try:
            batch.execute()
        except Exception as error:
            for message in messages[start : start + batch_size]:
                if message["id"] not in responses:
                    errors.setdefault(message["id"], error)
        if start + batch_size < len(messages):
            time.sleep(BATCH_PAUSE_SECONDS)

    metadata_failures = []
    for message in messages:
        message_id = message["id"]
        error = errors.get(message_id)
        if error is None:
            continue

        for attempt in range(1, METADATA_RETRY_ATTEMPTS):
            if not is_retriable_gmail_error(error):
                break
            time.sleep(RETRY_DELAYS_SECONDS[attempt - 1])
            try:
                responses[message_id] = _metadata_request(service, message_id).execute()
                error = None
                break
            except Exception as retry_error:
                error = retry_error

        if error is not None:
            metadata_failures.append((message_id, error))

    if metadata_failures and not allow_partial:
        first_error = metadata_failures[0][1]
        raise RuntimeError(
            f"Could not fetch metadata for {len(metadata_failures)} messages. "
            f"First error: {first_error}"
        )

    successful_messages = [
        responses[message["id"]] for message in messages if message["id"] in responses
    ]
    if allow_partial:
        return successful_messages, metadata_failures
    return successful_messages
