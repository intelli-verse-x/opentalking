from __future__ import annotations

import pytest

from opentalking.streaming.whip_sdp import WhipSdpError, validate_answer_sdp, validate_offer_sdp


OFFER = """v=0
a=group:BUNDLE 0 1
m=video 9 UDP/TLS/RTP/SAVPF 99
a=sendonly
a=rtcp-mux
a=ice-ufrag:u
a=ice-pwd:p
a=rtpmap:99 H264/90000
a=candidate:1 1 udp 1 8.8.8.8 4000 typ host
m=audio 9 UDP/TLS/RTP/SAVPF 111
a=sendonly
a=rtcp-mux
a=ice-ufrag:u
a=ice-pwd:p
a=rtpmap:111 opus/48000/2
a=candidate:1 1 udp 1 8.8.8.8 4001 typ host
"""

ANSWER = """v=0
a=group:BUNDLE 0 1
m=video 9 UDP/TLS/RTP/SAVPF 99
a=recvonly
a=rtcp-mux
a=ice-ufrag:u2
a=ice-pwd:p2
a=rtpmap:99 H264/90000
m=audio 9 UDP/TLS/RTP/SAVPF 111
a=recvonly
a=rtcp-mux
a=ice-ufrag:u2
a=ice-pwd:p2
a=rtpmap:111 opus/48000/2
"""


def test_whip_sdp_requires_codecs_directions_and_full_ice() -> None:
    validate_offer_sdp(OFFER)
    validate_answer_sdp(OFFER, ANSWER)
    with pytest.raises(WhipSdpError, match="sendonly"):
        validate_offer_sdp(OFFER.replace("a=sendonly", "a=recvonly", 1))
    with pytest.raises(WhipSdpError, match="candidates"):
        validate_offer_sdp(
            OFFER.replace("a=candidate:1 1 udp 1 8.8.8.8 4000 typ host\n", "").replace(
                "a=candidate:1 1 udp 1 8.8.8.8 4001 typ host\n", ""
            )
        )


def test_whip_sdp_rejects_private_candidate_without_local_test_mode() -> None:
    private_offer = OFFER.replace("8.8.8.8", "192.168.1.20")
    with pytest.raises(WhipSdpError, match="private host candidate"):
        validate_offer_sdp(private_offer)
    validate_offer_sdp(private_offer, allow_private_candidates=True)


def test_whip_sdp_relay_policy_requires_relay_candidates() -> None:
    with pytest.raises(WhipSdpError, match="relay candidate policy"):
        validate_offer_sdp(OFFER, candidate_policy="relay")
    relay_offer = OFFER.replace("typ host", "typ relay")
    validate_offer_sdp(relay_offer, candidate_policy="relay")


@pytest.mark.parametrize("target", ["127.0.0.1", "169.254.169.254", "10.1.2.3", "::1", "fd00::1"])
def test_whip_answer_rejects_unapproved_private_ice_targets(target: str) -> None:
    answer = ANSWER.replace(
        "a=recvonly\n", f"a=recvonly\na=candidate:1 1 udp 1 {target} 4000 typ host\n"
    )
    with pytest.raises(WhipSdpError, match="unapproved private ICE target"):
        validate_answer_sdp(OFFER, answer)


@pytest.mark.parametrize("target", ["internal.local", "invalid", "2001:4860::1%eth0"])
def test_whip_answer_rejects_unpinned_hostname_and_scoped_candidates(target: str) -> None:
    answer = ANSWER.replace(
        "a=recvonly\n", f"a=recvonly\na=candidate:1 1 udp 1 {target} 4000 typ host\n"
    )
    with pytest.raises(WhipSdpError, match="IP literal"):
        validate_answer_sdp(OFFER, answer)


def test_whip_answer_preserves_explicit_local_and_cidr_exceptions() -> None:
    answer = ANSWER.replace(
        "a=recvonly\n", "a=recvonly\na=candidate:1 1 udp 1 10.1.2.3 4000 typ host\n"
    )
    validate_answer_sdp(OFFER, answer, allow_private_candidates=True)
    validate_answer_sdp(OFFER, answer, allowed_cidrs=["10.1.2.0/24"])
    with pytest.raises(WhipSdpError, match="unapproved private ICE target"):
        validate_answer_sdp(OFFER, answer, allowed_cidrs=["10.2.0.0/16"])


@pytest.mark.parametrize("target", ["8.8.8.8", "2001:4860:4860::8888"])
def test_whip_answer_preserves_public_ice_targets(target: str) -> None:
    answer = ANSWER.replace(
        "a=recvonly\n", f"a=recvonly\na=candidate:1 1 udp 1 {target} 4000 typ host\n"
    )
    validate_answer_sdp(OFFER, answer)


@pytest.mark.parametrize("target", ["0.0.0.0", "::", "224.0.0.1", "ff02::1"])
def test_whip_answer_rejects_multicast_and_unspecified_targets_even_in_local_mode(
    target: str,
) -> None:
    answer = ANSWER.replace(
        "a=recvonly\n", f"a=recvonly\na=candidate:1 1 udp 1 {target} 4000 typ host\n"
    )
    with pytest.raises(WhipSdpError, match="invalid ICE target"):
        validate_answer_sdp(OFFER, answer, allow_private_candidates=True)
