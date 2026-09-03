"""Secret redaction for scanned file content.

Relocated verbatim from ``scanner.py`` (the regex passes are unchanged) so the
scanner stays under the module size limit once it grew skeletonisation. The
scanner re-imports ``_redact_secrets`` from here, so every fragment still
passes through it — the "redaction runs on every file's content" invariant
lives in ``scan_project``, not in where the regexes are defined.
"""

from __future__ import annotations

import re


def _redact_secrets(content: str) -> str:
    """Replace secret-like patterns in file content with redaction markers.

    This is a best-effort redaction — it catches common patterns but is not
    a substitute for proper secret management.
    """
    redacted = content

    # AWS access key IDs (AKIA...)
    redacted = re.sub(
        r'(AKIA[0-9A-Z]{16})',
        r'[REDACTED:AWS_ACCESS_KEY]',
        redacted,
    )

    # AWS secret access keys (40-char base64-like string, usually preceded by
    # "aws_secret_access_key" or similar context; the generic pattern catches
    # standalone values too)
    redacted = re.sub(
        r'(?i)(aws_secret[_\s]*(?:access_)?key)\s*[=\s:]\s*["\']?([A-Za-z0-9/+=]{40})["\']?',
        r'\1=[REDACTED:AWS_SECRET_KEY]',
        redacted,
    )

    # GitHub / GITHUB_TOKEN patterns
    redacted = re.sub(
        r'(?i)(gh[pousr]_[A-Za-z0-9_]{36,})',
        r'[REDACTED:GITHUB_TOKEN]',
        redacted,
    )

    # Generic bearer / API key assignments
    redacted = re.sub(
        r'(?i)((?:api[_-]?key|apikey)\s*[=:]\s*)["\']?([A-Za-z0-9_\-/+=]{20,})["\']?',
        r'\1"[REDACTED:API_KEY]"',
        redacted,
    )

    # Private key headers
    redacted = re.sub(
        r'(-----BEGIN (?:RSA |EC |DSA |OPENSSH )?PRIVATE KEY-----)',
        r'[REDACTED:PRIVATE_KEY_HEADER]',
        redacted,
    )
    redacted = re.sub(
        r'(-----END (?:RSA |EC |DSA |OPENSSH )?PRIVATE KEY-----)',
        r'[REDACTED:PRIVATE_KEY_HEADER]',
        redacted,
    )

    # Password assignments (KEY = value patterns)
    redacted = re.sub(
        r"(?i)((?:password|passwd|pwd)\s*[=:]\s*)([\"']?)(?!none|null|false|true|''|\"\"|\$\{)"
        r"[^\s\"',}]+\2",
        r"\1\2[REDACTED:PASSWORD]\2",
        redacted,
    )

    # Connection strings with embedded passwords
    redacted = re.sub(
        r'((?:mysql|postgres|postgresql|mongodb|redis|amqp)://[^:\s]+:)([^@\s]+)(@)',
        r'\1[REDACTED:CONN_STRING_PASSWORD]\3',
        redacted,
    )

    # Long random-looking strings assigned to variable names suggesting secrets
    redacted = re.sub(
        r'((?:secret|token|key|password|credential|auth)[^\s=]*\s*=\s*)["\']?([A-Za-z0-9_\-/+=]{32,})["\']?',
        r'\1"[REDACTED:SECRET]"',
        redacted,
        flags=re.IGNORECASE,
    )

    return redacted
