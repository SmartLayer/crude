"""Mautic REST transport: one instance, HTTP basic auth.

A MauticSession holds the instance base URL and a username/password pair, sent as
HTTP basic auth on every call. Mautic's own OAuth2 flow is the other supported
credential; basic auth is a per-instance switch (Configuration > API Settings >
Enable HTTP basic auth) and needs no token round trip, which is why it is the
credential this client carries.

Two shapes of the API are worth knowing before reading the resource layer. List
responses put the rows under a per-entity key that does not always match the URL
segment: ``/api/segments`` returns them under ``lists``, Mautic's older name for
the same object. And the rows arrive as a JSON object keyed by id for most
entities but as a plain array for forms, so `rows` normalises both to a list.

Submitted form values reach the API as they were stored, which for a value that
passed through an HTML form can mean entity-escaped text (``NDIS &amp; Disability``
beside ``NDIS & Disability`` for the same answer). `unescape_results` folds the two
so counting and grouping see one value, not two.
"""

from __future__ import annotations

import html

from crude_common import asof
from crude_common.httpapi import HttpSession

# The rows of a list response sit under a key that is not always the URL segment.
LIST_KEY = {
    "segments": "lists",
}

# Mautic rejects an oversized page rather than clamping it, so paging walks in
# steps of this size and the caller's --limit is applied on top.
PAGE = 100


class MauticError(RuntimeError):
    """A Mautic API error, carrying the HTTP status and Mautic's own error code."""

    def __init__(self, message, *, status=None, code=None):
        super().__init__(message)
        self.status = status
        self.code = code
        self.message = message


def list_key(entity: str) -> str:
    """The response key holding the rows for an entity's list endpoint."""
    return LIST_KEY.get(entity, entity)


def rows(payload: dict, entity: str) -> list:
    """The rows of a list response as a list, whichever shape the entity uses."""
    data = (payload or {}).get(list_key(entity))
    if isinstance(data, dict):
        return list(data.values())
    return data or []


def unescape_results(record: dict) -> dict:
    """Return a submission with HTML entities in its answers decoded.

    Applied before matching or grouping, so one answer stored two ways counts once.
    """
    results = record.get("results")
    if not isinstance(results, dict):
        return record
    decoded = {
        k: html.unescape(v) if isinstance(v, str) else v for k, v in results.items()
    }
    return {**record, "results": decoded}


class MauticSession(HttpSession):
    def __init__(self, base_url, username, password, *, timeout=60):
        super().__init__(base_url.rstrip("/") + "/api", timeout=timeout)
        self.instance_url = base_url.rstrip("/")
        self.session.auth = (username, password)
        self.session.headers.update({"Accept": "application/json"})

    def _raise(self, r) -> None:
        try:
            errors = r.json().get("errors") or []
        except ValueError:
            errors = []
        err = errors[0] if errors else {}
        code = err.get("code", r.status_code)
        msg = err.get("message") or f"HTTP {r.status_code}: {r.text[:200]}"
        if r.status_code in (401, 403):
            raise MauticError(
                f"{msg} The [mautic] credentials were rejected, or the API is off. "
                f"Both switches live in Configuration > API Settings: the API itself, "
                f"and HTTP basic auth.",
                status=r.status_code, code=code)
        raise MauticError(f"{msg} (code {code})", status=r.status_code, code=code)

    def get(self, path, *, params=None):
        return self._get(path, params=params)

    def iter_rows(self, path, entity, *, params=None, max_items=None):
        """Yield rows of a list endpoint, walking Mautic's start/limit paging.

        Stops on the reported total, on a short page, or once max_items is reached,
        so a caller asking for 20 of 7820 contacts makes one request.
        """
        p = dict(params or {})
        start, got = 0, 0
        while True:
            p.update({"start": start, "limit": PAGE})
            payload = self.get(path, params=p)
            page = rows(payload, entity)
            for item in page:
                yield item
                got += 1
                if max_items and got >= max_items:
                    return
            total = payload.get("total")
            start += len(page)
            if not page or (total is not None and start >= int(total)):
                return

    def fetch(self, path, entity, *, params=None, limit=None, created=None,
              modified=None, what=None):
        """A bounded list read: page, apply the WORLD_AS_OF cutoff, return rows.

        `created` names the row's creation-time field, which differs per entity
        (``dateAdded`` for most, ``dateSubmitted`` for a form submission), and
        `modified` names the edit stamp where the entity keeps one, so a record
        edited after the cutoff is served flagged rather than silently current. A
        form submission has no edit stamp: it is written once and not revised.

        The API offers no creation-time filter of its own, so the cutoff is applied
        here. Under one the whole set is walked before trimming to `limit`, so rows
        dropped for being too new do not eat into what the caller asked for.
        """
        bound = asof.world_as_of()
        if bound is None:
            return list(self.iter_rows(path, entity, params=params, max_items=limit))
        items = list(self.iter_rows(path, entity, params=params))
        kept = asof.bound_records(items, created, modified, what=what or entity)
        return kept[:limit] if limit else kept

    def one(self, path, entity_singular):
        """Fetch a single record, unwrapping Mautic's ``{"<entity>": {...}}`` envelope."""
        payload = self.get(path)
        return payload.get(entity_singular, payload)
