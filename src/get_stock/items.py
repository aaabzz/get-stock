import scrapy


class AnnouncementItem(scrapy.Item):
    stock_code = scrapy.Field()
    stock_name = scrapy.Field()
    org_id = scrapy.Field()
    exchange = scrapy.Field()
    announcement_id = scrapy.Field()
    title = scrapy.Field()
    category = scrapy.Field()
    document_type = scrapy.Field()
    document_role = scrapy.Field()
    report_type = scrapy.Field()
    report_period = scrapy.Field()
    is_full_report = scrapy.Field()
    is_summary = scrapy.Field()
    is_revision = scrapy.Field()
    content_validation_status = scrapy.Field()
    analysis_eligible = scrapy.Field()
    page_count = scrapy.Field()
    requires_ocr = scrapy.Field()
    validation_page_limit = scrapy.Field()
    validated_pages = scrapy.Field()
    matched_sections = scrapy.Field()
    validation_errors = scrapy.Field()
    published_at = scrapy.Field()
    pdf_url = scrapy.Field()
    local_path = scrapy.Field()
    download_status = scrapy.Field()
    crawled_at = scrapy.Field()
    file_urls = scrapy.Field()
    files = scrapy.Field()


class CompanyDatasetItem(scrapy.Item):
    dataset = scrapy.Field()
    stock_code = scrapy.Field()
    records = scrapy.Field()
    source_url = scrapy.Field()
    crawled_at = scrapy.Field()


class MarketDatasetItem(scrapy.Item):
    dataset = scrapy.Field()
    stock_code = scrapy.Field()
    records = scrapy.Field()
    source_url = scrapy.Field()
    crawled_at = scrapy.Field()


class FinancialDatasetItem(scrapy.Item):
    dataset = scrapy.Field()
    stock_code = scrapy.Field()
    records = scrapy.Field()
    source_url = scrapy.Field()
    crawled_at = scrapy.Field()


class ShareholderDatasetItem(scrapy.Item):
    dataset = scrapy.Field()
    stock_code = scrapy.Field()
    records = scrapy.Field()
    source_url = scrapy.Field()
    crawled_at = scrapy.Field()


class TradingDatasetItem(scrapy.Item):
    dataset = scrapy.Field()
    stock_code = scrapy.Field()
    records = scrapy.Field()
    source_url = scrapy.Field()
    crawled_at = scrapy.Field()
