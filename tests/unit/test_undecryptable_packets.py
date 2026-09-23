"""A packet we cannot read is still a packet.

When no configured key opened a packet, `decrypt_packet` raised
`DecryptionError`, which unwound to the caller, rolled the transaction
back and logged a traceback. Nothing was kept -- not even the fact
that two nodes had been on the air.

Add a channel, rotate a key, or have somebody use a channel this
deployment does not hold, and those nodes silently vanish from the map
while the log fills at packet rate. That is indistinguishable from a
quiet mesh, which is the worst way to lose data.

The PKI branch already did the right thing for a payload nobody here
can open: store it as traffic with an unknown port, because the port
number sits inside the encrypted part and both nodes were still heard.
This is the same case and now takes the same path.
"""

import inspect

from sonoran.ingest import pipeline


def test_a_packet_no_key_opens_is_stored_rather_than_dropped() -> None:
    """The fix, stated as the shape it has to have."""
    source = inspect.getsource(pipeline.process_message)
    assert "except DecryptionError:" in source, (
        "a packet no configured key opens still unwinds to the caller, "
        "so the transaction is rolled back and nothing is kept"
    )
    caught = source.index("except DecryptionError:")
    after = source[caught : caught + 1400]
    assert "_store_opaque(" in after, (
        "the undecryptable packet is caught but not stored; catching and "
        "dropping is the same loss with a quieter log"
    )


def test_it_takes_the_same_path_the_pki_case_already_took() -> None:
    """One way to store an unreadable payload, not two.

    If these diverge, one of them will grow a field the other lacks and
    the map will show two kinds of half-packet.
    """
    source = inspect.getsource(pipeline)
    assert source.count("_store_opaque(session, message, envelope, from_node_num)") == 2, (
        "the PKI path and the unknown-key path no longer share one way "
        "of storing a packet whose payload cannot be read"
    )


def test_the_loss_is_reported_rather_than_swallowed() -> None:
    """An operator who has mis-keyed a channel should be able to find out.

    Silence here would trade a traceback for nothing at all, which is
    worse: the packets would be stored and the cause invisible.
    """
    source = inspect.getsource(pipeline.process_message)
    caught = source.index("except DecryptionError:")
    after = source[caught : caught + 1400]
    assert "logger." in after, "nothing says a key failed to open a packet"
    assert "channel" in after, (
        "the log line does not name the channel, which is the one thing an operator needs to fix it"
    )
