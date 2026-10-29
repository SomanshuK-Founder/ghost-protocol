"""Fixed synthetic content and Mailpit-only submission. No routes or SMTP retries."""

import ipaddress
import smtplib
import socket
from email.message import EmailMessage
from email.policy import SMTP
from typing import Literal, Protocol
from uuid import uuid4

from app.gateway_contracts import EmailDraftResult, EmailSendResult
from app.services.email_profile import SENDER, arguments_for, recipient_allowed
from app.services.synthetic_executor import ExecutionInput, ExecutionOutcome

EMAIL_ERRORS = frozenset({"MAILPIT_NOT_ACCEPTED", "MAILPIT_UNCONFIRMED"})


class MailpitTransport(Protocol):
    def submit(
        self, recipient: str, message: bytes
    ) -> Literal["ACCEPTED", "REJECTED", "UNKNOWN"]: ...


class MailpitSMTP:
    """Trusted fixed service, one pinned RFC1918 IPv4, no public SMTP or fallback.

    shortcut: service identity depends on isolated deployment DNS/routing; validate Mailpit
    and disable its relay/forwarding before a separately approved runtime test.
    """

    def __init__(self, *, host="mailpit", port=1025, timeout=2.0):
        if host != "mailpit" or type(port) is not int or port != 1025:
            raise ValueError("Only the configured Mailpit service is supported")
        if type(timeout) not in (int, float) or not 0 < timeout <= 5:
            raise ValueError("A bounded Mailpit timeout is required")
        self._timeout = timeout

    def submit(self, recipient, message):
        # This is not a general message transport, including for trusted accidental callers.
        if not any(recipient_allowed(owner, recipient) for owner in ("local-user",)):
            return "REJECTED"
        client, data_started = None, False
        try:
            records = socket.getaddrinfo("mailpit", 1025, socket.AF_INET, socket.SOCK_STREAM)
            addresses = {record[4][0] for record in records}
            private = tuple(
                ipaddress.ip_network(net)
                for net in ("10.0.0.0/8", "172.16.0.0/12", "192.168.0.0/16")
            )
            if len(addresses) != 1 or not all(
                any(ipaddress.ip_address(addr) in net for net in private) for addr in addresses
            ):
                return "REJECTED"
            # Connect to the validated numeric address, with no second DNS lookup/fallback.
            client = smtplib.SMTP(timeout=self._timeout, local_hostname="ghost-demo.example.test")
            if client.connect(next(iter(addresses)), 1025)[0] != 220 or client.ehlo()[0] != 250:
                return "REJECTED"
            if client.mail(SENDER)[0] != 250 or client.rcpt(recipient)[0] not in (250, 251):
                return "REJECTED"
            data_started = True
            code, _ = client.data(message)
            if code == 250:
                return "ACCEPTED"
            return "REJECTED" if 400 <= code < 600 else "UNKNOWN"
        except smtplib.SMTPDataError as exc:
            # Unexpected positive replies are not proof of nonacceptance.
            return "REJECTED" if 400 <= exc.smtp_code < 600 else "UNKNOWN"
        except Exception:
            return "UNKNOWN" if data_started else "REJECTED"
        finally:
            if client is not None:
                try:
                    client.close()
                except Exception:
                    pass


class SyntheticEmailExecutor:
    def __init__(self, transport: MailpitTransport | None = None):
        self._transport = transport

    def execute(self, value: ExecutionInput) -> ExecutionOutcome:
        if (
            not isinstance(value, ExecutionInput)
            or value.action not in ("email.draft", "email.send")
            or value.context.mode
            != {"email.draft": "EMAIL_DRAFT", "email.send": "MAILPIT_SEND"}[value.action]
            or not recipient_allowed(value.email_owner, value.arguments.recipient)
            or value.arguments != arguments_for(value.arguments.recipient)
        ):
            raise ValueError("Unsupported synthetic email operation")
        if value.action == "email.draft":
            return ExecutionOutcome(
                "SUCCEEDED",
                EmailDraftResult(
                    draft_ref=f"draft_{uuid4().hex}", payload_digest=value.canonical_request_digest
                ),
            )
        if self._transport is None:
            return ExecutionOutcome("FAILED", sanitized_error_code="MAILPIT_NOT_ACCEPTED")
        message = EmailMessage(policy=SMTP)
        message["From"], message["To"] = SENDER, value.arguments.recipient
        message["Subject"] = value.arguments.subject
        message["Message-ID"] = f"<{value.context.attempt_ref}@ghost-demo.example.test>"
        message["X-Ghost-Transport"] = "MAILPIT-TEST-ONLY"
        # Bytes prevent the text content manager from adding a newline to the reviewed body.
        message.set_content(
            value.arguments.body.encode("utf-8"),
            maintype="text",
            subtype="plain",
            cte="base64",
            params={"charset": "utf-8"},
        )
        try:
            state = self._transport.submit(value.arguments.recipient, message.as_bytes())
        except Exception:
            state = "UNKNOWN"  # The injection boundary cannot prove whether DATA was accepted.
        if state == "ACCEPTED":
            return ExecutionOutcome(
                "SUCCEEDED", EmailSendResult(receipt_ref=f"receipt_{uuid4().hex}")
            )
        if state == "REJECTED":
            return ExecutionOutcome("FAILED", sanitized_error_code="MAILPIT_NOT_ACCEPTED")
        return ExecutionOutcome("UNKNOWN", sanitized_error_code="MAILPIT_UNCONFIRMED")
