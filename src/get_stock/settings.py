from get_stock.config import app_settings

BOT_NAME = "get_stock"

SPIDER_MODULES = ["get_stock.spiders"]
NEWSPIDER_MODULE = "get_stock.spiders"

ROBOTSTXT_OBEY = True
USER_AGENT = app_settings.user_agent

CONCURRENT_REQUESTS = 4
CONCURRENT_REQUESTS_PER_DOMAIN = 4
DOWNLOAD_DELAY = app_settings.download_delay
RANDOMIZE_DOWNLOAD_DELAY = True
DOWNLOAD_TIMEOUT = 30

RETRY_ENABLED = True
RETRY_TIMES = 2
RETRY_HTTP_CODES = [500, 502, 503, 504]

COOKIES_ENABLED = True
TELNETCONSOLE_ENABLED = False

DOWNLOADER_MIDDLEWARES = {
    "get_stock.middlewares.response_guard.ResponseGuardMiddleware": 560,
}

ITEM_PIPELINES = {
    "get_stock.pipelines.documents.CninfoFilesPipeline": 100,
    "get_stock.pipelines.jsonl.JsonLinesPipeline": 200,
}

DATA_DIR = str(app_settings.data_dir.resolve())
FILES_STORE = DATA_DIR
FILES_EXPIRES = 36500

LOG_LEVEL = "INFO"
LOG_FORMAT = "%(asctime)s [%(name)s] %(levelname)s: %(message)s"

REQUEST_FINGERPRINTER_IMPLEMENTATION = "2.7"
TWISTED_REACTOR = "twisted.internet.asyncioreactor.AsyncioSelectorReactor"
FEED_EXPORT_ENCODING = "utf-8"
