"""Linux user management utilities for agent provisioning.

All functions run as root via subprocess and are designed for use
by the WebUI agent management API.
"""

from __future__ import annotations

import logging
import subprocess

logger = logging.getLogger(__name__)

# UIDs below this threshold are considered system users
_MIN_REGULAR_UID = 1000


def user_exists(username: str) -> bool:
    """Check whether a Linux user exists."""
    result = subprocess.run(
        ["id", username],
        capture_output=True,
        check=False,
    )
    return result.returncode == 0


def create_linux_user(
    username: str,
    groups: list[str] | None = None,
    sudo_rules: list[str] | None = None,
    home_dir: str | None = None,
) -> bool:
    """Create a Linux user with optional groups, sudo rules, and home directory.

    Returns True on success, False on failure.
    """
    if user_exists(username):
        logger.info("User '%s' already exists, skipping creation", username)
        return True

    cmd = ["sudo", "useradd", "--create-home", "--shell", "/bin/bash"]
    if home_dir:
        cmd.extend(["--home-dir", home_dir])
    cmd.append(username)

    try:
        subprocess.run(cmd, capture_output=True, check=True)
    except subprocess.CalledProcessError:
        logger.exception("Failed to create user '%s'", username)
        return False

    # Add to groups
    if groups:
        for group in groups:
            subprocess.run(
                ["sudo", "groupadd", "--force", group],
                capture_output=True,
                check=False,
            )
        try:
            subprocess.run(
                ["sudo", "usermod", "-aG", ",".join(groups), username],
                capture_output=True,
                check=True,
            )
        except subprocess.CalledProcessError:
            logger.exception("Failed to add user '%s' to groups %s", username, groups)

    # Write sudoers rules
    if sudo_rules:
        sudoers_path = f"/etc/sudoers.d/{username}"
        rules = "\n".join(
            f"{username} ALL=(ALL) NOPASSWD: /usr/bin/{rule}" for rule in sudo_rules
        )
        content = f"# Managed by botwerk\n{rules}\n"
        try:
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
        except subprocess.CalledProcessError:
            logger.exception("Failed to write sudoers for '%s'", username)

    logger.info("Created Linux user '%s'", username)
    return True


def delete_linux_user(username: str) -> bool:
    """Delete a Linux user (preserves home directory).

    Returns True on success, False on failure.
    """
    if not user_exists(username):
        logger.info("User '%s' does not exist, nothing to delete", username)
        return True

    try:
        subprocess.run(
            ["sudo", "userdel", username],
            capture_output=True,
            check=True,
        )
    except subprocess.CalledProcessError:
        logger.exception("Failed to delete user '%s'", username)
        return False

    # Clean up sudoers file
    subprocess.run(
        ["sudo", "rm", "-f", f"/etc/sudoers.d/{username}"],
        capture_output=True,
        check=False,
    )

    logger.info("Deleted Linux user '%s'", username)
    return True


def list_linux_users() -> list[dict]:
    """List non-system Linux users (UID >= 1000, excluding 'nobody').

    Returns a list of dicts with keys: username, uid, groups, home.
    """
    users: list[dict] = []
    try:
        result = subprocess.run(
            ["getent", "passwd"],
            capture_output=True,
            check=True,
            text=True,
        )
    except subprocess.CalledProcessError:
        logger.exception("Failed to list users")
        return users

    for line in result.stdout.strip().splitlines():
        parts = line.split(":")
        if len(parts) < 7:
            continue
        username, _, uid_str, _, _, home, _ = parts[:7]
        try:
            uid = int(uid_str)
        except ValueError:
            continue
        if uid < _MIN_REGULAR_UID or username == "nobody":
            continue

        # Get groups for this user
        group_result = subprocess.run(
            ["groups", username],
            capture_output=True,
            check=False,
            text=True,
        )
        group_list = []
        if group_result.returncode == 0:
            # Output: "username : group1 group2 group3"
            group_part = group_result.stdout.strip().split(":")
            if len(group_part) > 1:
                group_list = group_part[1].strip().split()

        users.append({
            "username": username,
            "uid": uid,
            "groups": group_list,
            "home": home,
        })

    return users


def clone_linux_user(source: str, new_name: str) -> bool:
    """Clone a Linux user: copy groups and sudo config from source to new_name.

    Creates the new user if it does not exist.
    Returns True on success, False on failure.
    """
    if not user_exists(source):
        logger.error("Source user '%s' does not exist", source)
        return False

    # Get source groups
    try:
        result = subprocess.run(
            ["groups", source],
            capture_output=True,
            check=True,
            text=True,
        )
        group_part = result.stdout.strip().split(":")
        groups = group_part[1].strip().split() if len(group_part) > 1 else []
        # Remove the user's own primary group
        groups = [g for g in groups if g != source]
    except subprocess.CalledProcessError:
        groups = []

    # Get source sudo rules
    sudo_rules: list[str] = []
    source_sudoers = f"/etc/sudoers.d/{source}"
    try:
        result = subprocess.run(
            ["sudo", "cat", source_sudoers],
            capture_output=True,
            check=True,
            text=True,
        )
        for line in result.stdout.splitlines():
            line = line.strip()
            if line and not line.startswith("#"):
                # Extract the command part after NOPASSWD:
                parts = line.split("NOPASSWD:")
                if len(parts) > 1:
                    sudo_rules.append(parts[1].strip().removeprefix("/usr/bin/"))
    except subprocess.CalledProcessError:
        pass  # No sudoers file for source user

    return create_linux_user(new_name, groups=groups, sudo_rules=sudo_rules)
