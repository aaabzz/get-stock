from types import SimpleNamespace

import pytest
from scrapy.exceptions import CloseSpider
from scrapy.http import HtmlResponse, Request, TextResponse

from get_stock.middlewares.response_guard import ResponseGuardMiddleware


def make_spider(tmp_path):
    return SimpleNamespace(data_dir=str(tmp_path), stock_code="000001")


def test_guard_accepts_json_response(tmp_path) -> None:
    request = Request("https://example.test", meta={"expect_json": True})
    response = TextResponse(
        request=request,
        url=request.url,
        body=b'{"announcements":[]}',
        headers={"Content-Type": "application/json;charset=UTF-8"},
    )

    result = ResponseGuardMiddleware().process_response(request, response, make_spider(tmp_path))

    assert result is response


def test_guard_stops_on_403_and_saves_response(tmp_path) -> None:
    request = Request("https://example.test", meta={"expect_json": True})
    response = HtmlResponse(request=request, url=request.url, status=403, body=b"blocked")

    with pytest.raises(CloseSpider) as raised:
        ResponseGuardMiddleware().process_response(request, response, make_spider(tmp_path))

    assert raised.value.reason == "cninfo_http_403"
    saved = tmp_path / "stocks" / "000001" / "raw" / "http-403.txt"
    assert saved.read_bytes() == b"blocked"


def test_guard_stops_on_html_instead_of_json(tmp_path) -> None:
    request = Request("https://example.test", meta={"expect_json": True})
    response = HtmlResponse(
        request=request,
        url=request.url,
        status=200,
        body=b"<html><body>login</body></html>",
        headers={"Content-Type": "text/html"},
    )

    with pytest.raises(CloseSpider) as raised:
        ResponseGuardMiddleware().process_response(request, response, make_spider(tmp_path))

    assert raised.value.reason == "cninfo_unexpected_response"
