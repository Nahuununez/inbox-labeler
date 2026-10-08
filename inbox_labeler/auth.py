"""Gmail authentication: build the API client and run the one-time token setup.

``get_gmail_service()`` reads GMAIL_CLIENT_ID, GMAIL_CLIENT_SECRET and
GMAIL_REFRESH_TOKEN from the environment (or a local ``.env`` file).
"""

import os

from dotenv import load_dotenv
from google.oauth2.credentials import Credentials
from googleapiclient.discovery import build

load_dotenv()

# "gmail.modify" is the narrowest scope that lets the project add labels. It
# grants read/write access to the whole mailbox: the code only reads
# sender/subject headers and adds labels, but the token itself could do more.
SCOPES = ["https://www.googleapis.com/auth/gmail.modify"]
REQUIRED_VARIABLES = ("GMAIL_CLIENT_ID", "GMAIL_CLIENT_SECRET", "GMAIL_REFRESH_TOKEN")


def get_gmail_service():
    missing = [name for name in REQUIRED_VARIABLES if not os.environ.get(name)]
    if missing:
        raise RuntimeError(
            f"Missing environment variables: {', '.join(missing)}. "
            "Copy .env.example to .env (local use) or add them as GitHub "
            "secrets (Actions). See the README."
        )
    # The access token is fetched on demand from the refresh token, so no
    # browser window is needed after the one-time setup.
    creds = Credentials(
        token=None,
        refresh_token=os.environ["GMAIL_REFRESH_TOKEN"],
        client_id=os.environ["GMAIL_CLIENT_ID"],
        client_secret=os.environ["GMAIL_CLIENT_SECRET"],
        token_uri="https://oauth2.googleapis.com/token",
        scopes=SCOPES,
    )
    return build("gmail", "v1", credentials=creds, cache_discovery=False)


def check_connection():
    """Print only the mailbox message count; never senders or subjects."""
    profile = get_gmail_service().users().getProfile(userId="me").execute()
    print("Connected to Gmail.")
    print(f"Messages in mailbox: {profile.get('messagesTotal')}")


def authorize(client_secrets_file="client_secret.json"):
    """One-time, local: open the browser consent screen and print the 3 values.

    The values are printed in plain text. Store them as GitHub secrets (and
    optionally in a local .env); never paste them in issues, chats or commits.
    If one leaks, revoke access at https://myaccount.google.com/permissions.
    """
    from google_auth_oauthlib.flow import InstalledAppFlow

    flow = InstalledAppFlow.from_client_secrets_file(client_secrets_file, SCOPES)
    creds = flow.run_local_server(port=0)
    print("\n--- SAVE THESE AS GITHUB SECRETS (and keep them private) ---")
    print("GMAIL_CLIENT_ID:", creds.client_id)
    print("GMAIL_CLIENT_SECRET:", creds.client_secret)
    print("GMAIL_REFRESH_TOKEN:", creds.refresh_token)
    print("-------------------------------------------------------------")
    print("\nDo NOT commit these values or client_secret.json.")
