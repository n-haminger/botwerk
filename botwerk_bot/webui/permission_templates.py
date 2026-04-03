"""Permission templates for agent Linux users.

Three built-in templates define groups, sudo rules, and descriptions
for provisioning agent Linux users with appropriate access levels.
"""

from __future__ import annotations

import logging
import subprocess

from pydantic import BaseModel

logger = logging.getLogger(__name__)


class PermissionTemplate(BaseModel):
    """A named permission template for Linux user provisioning."""

    name: str
    description: str
    groups: list[str]
    sudo_rules: list[str]


# Built-in templates
_TEMPLATES: dict[str, PermissionTemplate] = {
    "developer": PermissionTemplate(
        name="developer",
        description="Developer access: developers group, no sudo, restricted home directory",
        groups=["developers"],
        sudo_rules=[],
    ),
    "ops": PermissionTemplate(
        name="ops",
        description="Operations access: ops group, sudo for systemctl/journalctl/apt",
        groups=["ops"],
        sudo_rules=["systemctl *", "journalctl *", "apt *"],
    ),
    "restricted": PermissionTemplate(
        name="restricted",
        description="Minimal access: no groups, no sudo, home directory only",
        groups=[],
        sudo_rules=[],
    ),
}


def get_templates() -> list[PermissionTemplate]:
    """Return all built-in permission templates."""
    return list(_TEMPLATES.values())


def get_template(name: str) -> PermissionTemplate | None:
    """Return a single template by name, or None if not found."""
    return _TEMPLATES.get(name)


def apply_template(username: str, template_name: str) -> bool:
    """Apply a permission template to an existing Linux user.

    Sets group memberships and writes sudoers rules.
    Returns True on success, False on failure.
    """
    template = _TEMPLATES.get(template_name)
    if template is None:
        logger.error("Unknown permission template: %s", template_name)
        return False

    try:
        # Set group memberships (replaces supplementary groups)
        if template.groups:
            # Ensure groups exist
            for group in template.groups:
                subprocess.run(
                    ["sudo", "groupadd", "--force", group],
                    capture_output=True,
                    check=False,
                )
            subprocess.run(
                ["sudo", "usermod", "-G", ",".join(template.groups), username],
                capture_output=True,
                check=True,
            )
        else:
            # Remove all supplementary groups
            subprocess.run(
                ["sudo", "usermod", "-G", "", username],
                capture_output=True,
                check=True,
            )

        # Write sudoers rules
        sudoers_path = f"/etc/sudoers.d/{username}"
        if template.sudo_rules:
            rules = "\n".join(
                f"{username} ALL=(ALL) NOPASSWD: /usr/bin/{rule}"
                for rule in template.sudo_rules
            )
            content = f"# Managed by botwerk - template: {template_name}\n{rules}\n"
            subprocess.run(
                ["sudo", "tee", sudoers_path],
                input=content.encode(),
                capture_output=True,
                check=True,
            )
            subprocess.run(
                ["sudo", "chmod", "0440", sudoers_path],
                capture_output=True,
                check=True,
            )
        else:
            # Remove sudoers file if it exists
            subprocess.run(
                ["sudo", "rm", "-f", sudoers_path],
                capture_output=True,
                check=True,
            )

    except subprocess.CalledProcessError:
        logger.exception("Failed to apply template '%s' to user '%s'", template_name, username)
        return False

    logger.info("Applied template '%s' to user '%s'", template_name, username)
    return True
