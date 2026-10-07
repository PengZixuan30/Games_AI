"""An enrolled instance must never take the hub role (the role-swap guard).

The scenario this protects against: a node finishes its update and loads while the hub is
still down (or is itself being updated). `decide_mode` used to answer "the port is free, so I
am the hub now" -- the real hub then comes back, sees a GamesAI hub answering, and becomes
*its* client. The two roles have swapped for good. Now an instance holding a node token stays
a client, and the escape hatch is `!!gamesai node forget` (which drops the token).
"""
import logging

from games_ai import cross_server as cs
from games_ai.websockets_server import CrossServerHub

log = logging.getLogger("gamesai_pin")
HOST = "127.0.0.1"


def _silent_uri(free_port):
    """A ws:// address nothing listens on: a decision here is a decision on a free port."""
    return "ws://{}:{}".format(HOST, free_port())


def test_a_free_local_port_is_still_served_without_a_token(free_port):
    mode, reason = cs.decide_mode(_silent_uri(free_port), force_server=False, logger=log, grace=0.3)

    assert mode == cs.MODE_SERVER, \
        f"without a token the instance may serve that address (unchanged): {(mode, reason)}"


def test_an_enrolled_instance_never_takes_the_port(free_port):
    mode, reason = cs.decide_mode(_silent_uri(free_port), force_server=False, logger=log,
                                  token="a-node-token", previous_role=cs.MODE_CLIENT, grace=0.3)
    assert mode == cs.MODE_CLIENT, \
        f"an enrolled client stays a client instead of taking the port: {(mode, reason)}"
    assert "node forget" in reason, f"and the reason tells the operator what to do: {reason}"

    mode, reason = cs.decide_mode(_silent_uri(free_port), force_server=False, logger=log,
                                  token="a-node-token", grace=0.3)
    assert mode == cs.MODE_CLIENT, \
        f"a token alone is enough (a fresh claim has no role memory yet): {(mode, reason)}"

    mode, reason = cs.decide_mode(_silent_uri(free_port), force_server=False, logger=log,
                                  token="a-node-token", previous_role=cs.MODE_SERVER, grace=0.3)
    assert mode == cs.MODE_SERVER, \
        f"an instance that was the hub keeps being the hub, token or not: {(mode, reason)}"

    mode, reason = cs.decide_mode(_silent_uri(free_port), force_server=True, logger=log,
                                  token="a-node-token", previous_role=cs.MODE_CLIENT, grace=0.3)
    assert mode == cs.MODE_SERVER, \
        f"force_server still wins: an explicit operator choice beats the pin: {(mode, reason)}"

    mode, reason = cs.decide_mode(_silent_uri(free_port), force_server=False, logger=log,
                                  previous_role=cs.MODE_CLIENT, grace=0.3)
    assert mode == cs.MODE_SERVER, \
        f"after !!gamesai node forget (no token) the old takeover still works: {(mode, reason)}"


def test_an_address_this_machine_cannot_serve_is_unchanged(free_port, monkeypatch):
    monkeypatch.setattr(cs, "is_servable", lambda host: False)

    mode, reason = cs.decide_mode(_silent_uri(free_port), force_server=False, logger=log,
                                  token="a-node-token", grace=0.3)

    assert mode == cs.MODE_LOCAL, f"a dial-only address stays local, token or not: {(mode, reason)}"


def test_a_live_hub_is_still_joined_as_a_client(free_port):
    port = free_port()
    hub = CrossServerHub(HOST, port, name="hub", logger=log)
    assert hub.start(timeout=5), f"the test hub started: {hub.is_running}"
    try:
        uri = "ws://{}:{}".format(HOST, port)
        mode, reason = cs.decide_mode(uri, force_server=False, logger=log, token="a-node-token",
                                      previous_role=cs.MODE_CLIENT, grace=2.0)
        assert mode == cs.MODE_CLIENT, f"a hub that answers is joined: {(mode, reason)}"
        assert "answered" in reason, f"the reason names the hub: {reason}"

        mode, reason = cs.decide_mode(uri, force_server=False, logger=log, grace=2.0)
        assert mode == cs.MODE_CLIENT, f"an instance without a token also joins it: {(mode, reason)}"
    finally:
        hub.stop(timeout=3)
