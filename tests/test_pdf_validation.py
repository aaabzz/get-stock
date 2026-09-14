from get_stock import pdf_validation


class FakePage:
    def __init__(self, text: str) -> None:
        self.text = text

    def extract_text(self) -> str:
        return self.text


class FakeReader:
    is_encrypted = False

    def __init__(self, pages: list[str]) -> None:
        self.pages = [FakePage(text) for text in pages]


def test_full_report_pdf_validation_accepts_matching_sections(monkeypatch, tmp_path) -> None:
    text = """
    平安银行股份有限公司 2025年年度报告
    第三节 管理层讨论与分析
    第四节 公司治理
    第六节 重要事项
    第七节 股份变动及股东情况
    第十节 财务报告
    """ + ("业务数据" * 200)
    monkeypatch.setattr(
        pdf_validation,
        "PdfReader",
        lambda path, strict=False: FakeReader([text, "财务报表"]),
    )

    result = pdf_validation.validate_full_report_pdf(
        tmp_path / "full.pdf",
        stock_name="平安银行",
        report_type="annual",
        report_period="2025-12-31",
    )

    assert result["content_validation_status"] == "passed"
    assert result["analysis_eligible"] is True
    assert result["page_count"] == 2
    assert result["requires_ocr"] is False
    assert result["validation_page_limit"] == 20
    assert result["validated_pages"] == 2
    assert len(result["matched_sections"]) >= 3
    assert result["validation_errors"] == []


def test_full_report_pdf_validation_rejects_summary(monkeypatch, tmp_path) -> None:
    text = "平安银行 2025年年度报告摘要" + ("摘要内容" * 200)
    monkeypatch.setattr(
        pdf_validation,
        "PdfReader",
        lambda path, strict=False: FakeReader([text]),
    )

    result = pdf_validation.validate_full_report_pdf(
        tmp_path / "summary.pdf",
        stock_name="平安银行",
        report_type="annual",
        report_period="2025-12-31",
    )

    assert result["content_validation_status"] == "failed"
    assert result["analysis_eligible"] is False
    assert "summary_detected" in result["validation_errors"]
    assert "insufficient_full_report_sections" in result["validation_errors"]


def test_full_report_pdf_validation_handles_unreadable_pdf(monkeypatch, tmp_path) -> None:
    def fail_reader(path, strict=False):
        raise ValueError("broken")

    monkeypatch.setattr(pdf_validation, "PdfReader", fail_reader)

    result = pdf_validation.validate_full_report_pdf(
        tmp_path / "broken.pdf",
        stock_name="平安银行",
        report_type="annual",
        report_period="2025-12-31",
    )

    assert result["content_validation_status"] == "failed"
    assert result["analysis_eligible"] is False
    assert result["validation_errors"] == ["pdf_read_error:ValueError"]
    assert result["validation_page_limit"] == 20


def test_full_report_validation_stops_when_evidence_is_found(monkeypatch, tmp_path) -> None:
    cover = "平安银行 2025年年度报告" + ("公司信息" * 200)
    contents = "管理层讨论与分析 公司治理 重要事项 财务报告"
    pages = [cover, "重要提示", "目录", contents] + ["正文"] * 30
    reader = FakeReader(pages)
    monkeypatch.setattr(pdf_validation, "PdfReader", lambda path, strict=False: reader)

    result = pdf_validation.validate_full_report_pdf(
        tmp_path / "full.pdf",
        stock_name="平安银行",
        report_type="annual",
        report_period="2025-12-31",
    )

    assert result["content_validation_status"] == "passed"
    assert result["validated_pages"] == 4


def test_full_report_validation_expands_past_ten_pages_when_needed(monkeypatch, tmp_path) -> None:
    cover = "平安银行 2025年年度报告" + ("公司信息" * 200)
    pages = [cover] + ["重要提示"] * 10 + ["管理层讨论与分析 公司治理 重要事项 财务报告"]
    monkeypatch.setattr(
        pdf_validation,
        "PdfReader",
        lambda path, strict=False: FakeReader(pages),
    )

    result = pdf_validation.validate_full_report_pdf(
        tmp_path / "full.pdf",
        stock_name="平安银行",
        report_type="annual",
        report_period="2025-12-31",
    )

    assert result["content_validation_status"] == "passed"
    assert result["validated_pages"] == 12
