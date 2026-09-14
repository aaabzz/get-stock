from pathlib import Path

from scrapy.exceptions import CloseSpider
from scrapy.http import Request, Response


class ResponseGuardMiddleware:
    """Stop safely when CNINFO returns blocking or non-JSON responses."""

    def process_response(self, request: Request, response: Response, spider):
        if response.status in {403, 429}:
            self._save_blocked_response(response, spider, f"http-{response.status}")
            raise CloseSpider(reason=f"cninfo_http_{response.status}")

        if request.meta.get("expect_json"):
            content_type = response.headers.get(b"Content-Type", b"").decode(
                "latin-1", errors="ignore"
            )
            stripped = response.body.lstrip().lower()
            looks_like_html = stripped.startswith((b"<!doctype html", b"<html"))
            looks_like_captcha = any(
                marker in stripped for marker in ("验证码".encode(), b"captcha", b"verifycode")
            )
            if "json" not in content_type.lower() or looks_like_html or looks_like_captcha:
                self._save_blocked_response(response, spider, "unexpected-response")
                raise CloseSpider(reason="cninfo_unexpected_response")

        return response

    @staticmethod
    def _save_blocked_response(response: Response, spider, label: str) -> None:
        raw_dir = Path(spider.data_dir) / "stocks" / spider.stock_code / "raw"
        raw_dir.mkdir(parents=True, exist_ok=True)
        (raw_dir / f"{label}.txt").write_bytes(response.body)
