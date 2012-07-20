"""
Fabric tools for managing OpenVZ containers
"""
from contextlib import contextmanager

from fabric.state import env, output, default_channel
from fabric.utils import error

from fabric.operations import (
    _AttributeString,
    _execute,
    _prefix_commands,
    _prefix_env_vars,
    _shell_wrap,
    _sudo_prefix,
    )
import fabric.operations


@contextmanager
def guest(name_or_ctid):
    """
    Context manager to run commands inside a guest container

    Warning: commands executed with run() will be run as root
    inside the container. Use sudo(command, user='foo') to run
    them as an unpriviledged user.
    """

    # Monkey patch fabric's _run_command
    _orig_run_command = fabric.operations._run_command

    def run_guest_command(command, shell=True, pty=False,
        combine_stderr=True, sudo=False, user=None):
        """
        Run command inside a guest container
        """

        # Use a non-login shell
        _orig_shell = env.shell
        env.shell = '/bin/bash -c'

        # Use double quotes for the sudo prompt
        _orig_sudo_prefix = env.sudo_prefix
        env.sudo_prefix = 'sudo -S -p "%(sudo_prompt)s" '

        # Build the guest command
        guest_command = _shell_wrap_inner(
            _prefix_commands(_prefix_env_vars(command), 'remote'),
            True,
            _sudo_prefix(user) if sudo and user else None
        )
        host_command = "vzctl exec2 %s '%s'" % (name_or_ctid, guest_command)

        # Restore env
        env.shell = _orig_shell
        env.sudo_prefix = _orig_sudo_prefix

        # Run host command as root
        return _run_host_command(host_command, shell=shell, pty=pty,
            combine_stderr=combine_stderr)

    fabric.operations._run_command = run_guest_command

    yield

    # Monkey unpatch
    fabric.operations._run_command = _orig_run_command


def _run_host_command(command, shell=True, pty=True, combine_stderr=True):
    """
    Run host wrapper command as root

    (Modified from fabric.operations._run_command to ignore prefixes,
    path(), cd(), and always use sudo.)
    """
    # Set up new var so original argument can be displayed verbatim later.
    given_command = command
    # Handle context manager modifications, and shell wrapping
    wrapped_command = _shell_wrap(
        command,
        shell,
        _sudo_prefix(None)
    )
    # Execute info line
    if output.debug:
        print("[%s] %s: %s" % (env.host_string, 'sudo', wrapped_command))
    elif output.running:
        print("[%s] %s: %s" % (env.host_string, 'sudo', given_command))

    # Actual execution, stdin/stdout/stderr handling, and termination
    stdout, stderr, status = _execute(default_channel(), wrapped_command, pty,
        combine_stderr)

    # Assemble output string
    out = _AttributeString(stdout)
    err = _AttributeString(stderr)

    # Error handling
    out.failed = False
    if status != 0:
        out.failed = True
        msg = "%s() received nonzero return code %s while executing" % (
            'sudo', status
        )
        if env.warn_only:
            msg += " '%s'!" % given_command
        else:
            msg += "!\n\nRequested: %s\nExecuted: %s" % (
                given_command, wrapped_command
            )
        error(message=msg, stdout=out, stderr=err)

    # Attach return code to output string so users who have set things to
    # warn only, can inspect the error code.
    out.return_code = status

    # Convenience mirror of .failed
    out.succeeded = not out.failed

    # Attach stderr for anyone interested in that.
    out.stderr = err

    return out


def _shell_wrap_inner(command, shell=True, sudo_prefix=None):
    """
    Conditionally wrap given command in env.shell (while honoring sudo.)

    (Modified from fabric.operations._shell_wrap to avoid double escaping,
    as the wrapping host command would also get shell escaped.)
    """
    # Honor env.shell, while allowing the 'shell' kwarg to override it (at
    # least in terms of turning it off.)
    if shell and not env.use_shell:
        shell = False
    # Sudo plus space, or empty string
    if sudo_prefix is None:
        sudo_prefix = ""
    else:
        sudo_prefix += " "
    # If we're shell wrapping, prefix shell and space, escape the command and
    # then quote it. Otherwise, empty string.
    if shell:
        shell = env.shell + " "
        command = '"%s"' % command
    else:
        shell = ""
    # Resulting string should now have correct formatting
    return sudo_prefix + shell + command