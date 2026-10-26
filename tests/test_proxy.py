import pytest

from src.proxy import ProxyParseError, parse_proxy, parse_proxy_list


@pytest.mark.parametrize(
    "raw, expected",
    [
        ("1.2.3.4:8080", "http://1.2.3.4:8080"),
        ("silver.ciaude.co.uk:3128", "http://silver.ciaude.co.uk:3128"),
        ("silver.ciaude.co.uk:8080:user:pass", "http://user:pass@silver.ciaude.co.uk:8080"),
        ("user:pass@silver.ciaude.co.uk:8080", "http://user:pass@silver.ciaude.co.uk:8080"),
        ("user:pass:1.2.3.4:8080", "http://user:pass@1.2.3.4:8080"),
        ("1.2.3.4:8080@user:pass", "http://user:pass@1.2.3.4:8080"),
        ("socks5://user:pass@host.example.com:1080", "socks5://user:pass@host.example.com:1080"),
        ("https://host.example.com:443", "https://host.example.com:443"),
        ("[2001:db8::1]:8080", "http://[2001:db8::1]:8080"),
        ("host.example.com:8080:user:p:a:ss", "http://user:p%3Aa%3Ass@host.example.com:8080"),
    ],
)
def test_parse_proxy_formats(raw, expected):
    assert parse_proxy(raw).url == expected


def test_masked_hides_password():
    proxy = parse_proxy("user:supersecret@1.2.3.4:8080")
    assert "supersecret" not in proxy.masked
    assert "•••" in proxy.masked


@pytest.mark.parametrize("raw", ["", "not-a-proxy", "host:99999", "host:notaport", "ftp://host:21"])
def test_parse_proxy_rejects_garbage(raw):
    with pytest.raises(ProxyParseError):
        parse_proxy(raw)


def test_parse_proxy_list():
    pool = parse_proxy_list("1.1.1.1:80\nuser:pass@2.2.2.2:3128, socks5://3.3.3.3:1080")
    assert [p.port for p in pool] == [80, 3128, 1080]
    assert pool[2].scheme == "socks5"
