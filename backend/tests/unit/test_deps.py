from app.api.deps import collapse_ipv6


def test_ipv4_address_is_left_exact() -> None:
    assert collapse_ipv6("203.0.113.42") == "203.0.113.42"


def test_ipv6_address_is_collapsed_to_its_64_network() -> None:
    assert collapse_ipv6("2001:db8:1234:5678:aaaa:bbbb:cccc:dddd") == "2001:db8:1234:5678::"


def test_two_ipv6_addresses_in_the_same_64_network_collapse_to_the_same_value() -> None:
    first = collapse_ipv6("2001:db8:1234:5678::1")
    second = collapse_ipv6("2001:db8:1234:5678:ffff:ffff:ffff:ffff")

    assert first == second


def test_ipv6_addresses_in_different_64_networks_stay_distinct() -> None:
    assert collapse_ipv6("2001:db8:1234:5678::1") != collapse_ipv6("2001:db8:1234:5679::1")


def test_non_ip_strings_pass_through_unchanged() -> None:
    assert collapse_ipv6("unknown") == "unknown"
    assert collapse_ipv6("testclient") == "testclient"
