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


def _code_only(source: str) -> str:
    """Return `source` with comments removed.

    A test that greps source text answers from whatever is in the file,
    and a comment explaining a rule reads exactly like the rule. That
    has produced a false pass in this repository four times -- most
    memorably a check for `--set` that found the comment forbidding it.
    """
    lines = []
    for line in source.splitlines():
        code = line.split("#", 1)[0].rstrip()
        if code:
            lines.append(code)
    return "\n".join(lines)


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

    This used to match the call text exactly, and #157 broke it by
    adding an argument without changing anything it meant to protect.
    It now matches the call *site* and reads the argument, which is both
    less brittle and a stronger claim: the two paths still share one
    function, and they no longer pass it the same thing.
    """
    source = inspect.getsource(pipeline)
    calls = [
        line for line in source.splitlines() if "_store_opaque(" in line and "async def" not in line
    ]
    assert len(calls) == 2, (
        "the PKI path and the unknown-key path no longer share one way "
        f"of storing a packet whose payload cannot be read: {calls}"
    )


def test_the_two_unreadable_paths_record_different_reasons() -> None:
    """Sharing a function must not mean losing the distinction (#157).

    A census over a 168 h production window found these two paths are
    91.7% and 8.2% of every stored `portnum = 0` row, and they are not
    the same event: a no-key packet becomes readable the moment somebody
    adds the channel, and a PKI packet never does. The test above holds
    them to one code path; this one holds that path to telling them
    apart.
    """
    code = _code_only(inspect.getsource(pipeline.process_message))
    assert "PayloadState.PKI" in code, "the PKI path no longer records that it was PKI"
    assert "PayloadState.NO_KEY" in code, (
        "the unknown-key path no longer records that a key was missing"
    )


def test_the_comment_stripper_does_not_answer_from_a_comment() -> None:
    """The positive control for the test above.

    Every source-text assertion in this repository has to answer the
    same question: is it reading the code, or a comment that happens to
    mention the code? Searching raw source has produced a false pass
    here four times. This proves the strainer catches what it is for.
    """
    assert _code_only("x = 1  # PayloadState.PKI") == "x = 1"
    assert _code_only("# PayloadState.PKI\ny = 2") == "y = 2"
    assert "PayloadState.PKI" in _code_only("state = PayloadState.PKI")


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
