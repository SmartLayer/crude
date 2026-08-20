"""Heartbeat for crude-mautic.

``status`` confirms the configured credentials reach the instance and prints the
signed-in user, so a rejected password or an API left switched off is caught with
one clean call before any resource command runs.
"""

from __future__ import annotations

import typer

from crude_common.output import emit_record
from crude_mautic.client import MauticError

_JSON = typer.Option(False, "--json", help="Print the raw JSON of the result.")


def _session():
    from crude_mautic.cli import _session as impl

    return impl()


def status(output_json: bool = _JSON):
    """Confirm the credentials and print the instance and signed-in user."""
    sess = _session()
    try:
        me = sess.get("/users/self")
    except MauticError as e:
        typer.echo(f"Credential check failed: {e}", err=True)
        raise typer.Exit(1)
    rec = {
        "instance": sess.instance_url,
        "user_id": me.get("id"),
        "username": me.get("username"),
        "name": " ".join(x for x in (me.get("firstName"), me.get("lastName")) if x),
        "email": me.get("email"),
    }
    if not output_json:
        typer.echo("Credentials valid.")
    emit_record(rec, output_json)


def register(app_root: typer.Typer) -> None:
    """Attach the status command to the root."""
    app_root.command("status")(status)
