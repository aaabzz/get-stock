"""Stable synthesis topics and source policies."""

from typing import Final

SOURCE_LABELS: Final[dict[str, str]] = {
    "financial_analysis": "财务分析 Agent",
    "market_trading": "市场交易 Agent",
    "shareholder_analysis": "股东分析 Agent",
    "financial_report_analysis": "财报定性分析 Agent",
}

TOPIC_LABELS: Final[dict[str, str]] = {
    "financial_performance": "财务表现",
    "profitability": "盈利能力",
    "earnings_quality": "盈利质量",
    "balance_sheet": "资产负债",
    "solvency": "偿债能力",
    "operating_efficiency": "运营效率",
    "cash_flow": "现金流",
    "dividends": "分红",
    "capital_structure": "股本结构",
    "market_price_trend": "价格趋势",
    "volatility": "波动风险",
    "liquidity": "流动性",
    "price_volume": "价量关系",
    "valuation": "估值",
    "margin_activity": "融资融券",
    "block_trades": "大宗交易",
    "ownership_structure": "持股结构",
    "shareholder_concentration": "股东集中度",
    "holder_changes": "主要股东变化",
    "shareholder_count": "股东人数",
    "fund_holdings": "基金持股",
    "restricted_unlocks": "限售解禁",
    "equity_pledges": "股权质押",
    "business_overview": "主营业务",
    "industry_position": "行业地位",
    "market_share": "市场份额",
    "competitive_advantage": "竞争优势",
    "technology_advantage": "技术优势",
    "research_development": "研发情况",
    "growth_drivers": "增长驱动",
    "management_explanation": "管理层解释",
    "business_risks": "经营风险",
    "customer_supplier_dependency": "客户与供应商依赖",
    "development_strategy": "发展战略",
}
