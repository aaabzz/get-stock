"""Capabilities and heading-based retrieval policy for the report agent."""

from typing import Final

ALLOWED_SECTION_TYPES: Final[frozenset[str]] = frozenset(
    {
        "company_profile",
        "business_overview",
        "management_discussion",
        "corporate_governance",
        "environment_social",
        "important_matters",
        "shareholders",
        "bonds",
    }
)

DENIED_SECTION_TYPES: Final[frozenset[str]] = frozenset(
    {"financial_indicators", "financial_report", "front_matter", "unclassified"}
)

DENIED_HEADING_ALIASES: Final[tuple[str, ...]] = (
    "会计数据和财务指标",
    "财务报告",
    "财务报表",
    "审计报告",
    "财务报表附注",
)

REPORT_TOPIC_CATALOG: Final[dict[str, dict[str, tuple[str, ...]]]] = {
    "business_overview": {
        "preferred_sections": ("company_profile", "business_overview"),
        "heading_aliases": ("公司简介", "公司业务概要", "公司业务概述", "公司主要业务"),
        "keywords": ("主营业务", "主要业务", "业务模式", "产品", "服务"),
    },
    "industry_position": {
        "preferred_sections": ("company_profile", "business_overview", "management_discussion"),
        "heading_aliases": ("公司简介", "公司业务概要", "管理层讨论与分析", "经营情况讨论与分析"),
        "keywords": ("行业地位", "市场地位", "市场排名", "竞争格局", "领先", "行业"),
    },
    "market_share_disclosure": {
        "preferred_sections": ("company_profile", "business_overview", "management_discussion"),
        "heading_aliases": ("公司简介", "公司业务概要", "管理层讨论与分析", "经营情况讨论与分析"),
        "keywords": ("市场份额", "市占率", "市场占有率", "排名"),
    },
    "competitive_advantage": {
        "preferred_sections": ("company_profile", "business_overview", "management_discussion"),
        "heading_aliases": ("公司简介", "公司业务概要", "管理层讨论与分析", "经营情况讨论与分析"),
        "keywords": ("核心竞争力", "竞争优势", "差异化", "品牌优势", "平台优势"),
    },
    "technology_advantage": {
        "preferred_sections": ("company_profile", "business_overview", "management_discussion"),
        "heading_aliases": ("公司简介", "公司业务概要", "管理层讨论与分析", "经营情况讨论与分析"),
        "keywords": ("核心技术", "技术平台", "科技赋能", "数字化", "人工智能", "专利"),
    },
    "research_and_development": {
        "preferred_sections": ("business_overview", "management_discussion"),
        "heading_aliases": ("公司业务概要", "管理层讨论与分析", "经营情况讨论与分析"),
        "keywords": ("研发", "研究开发", "研发项目", "研发人员", "技术创新"),
    },
    "growth_drivers": {
        "preferred_sections": ("business_overview", "management_discussion"),
        "heading_aliases": ("公司业务概要", "管理层讨论与分析", "经营情况讨论与分析"),
        "keywords": ("增长", "增长动力", "驱动", "发展机遇", "业务拓展"),
    },
    "management_explanation": {
        "preferred_sections": ("management_discussion",),
        "heading_aliases": ("管理层讨论与分析", "经营情况讨论与分析", "董事会报告"),
        "keywords": ("主要由于", "原因", "影响", "同比", "变化", "下降", "增长"),
    },
    "business_risks": {
        "preferred_sections": ("management_discussion", "important_matters"),
        "heading_aliases": ("管理层讨论与分析", "经营情况讨论与分析", "重要事项"),
        "keywords": ("风险", "不确定性", "压力", "挑战", "重大诉讼"),
    },
    "customer_supplier_dependency": {
        "preferred_sections": ("business_overview", "management_discussion"),
        "heading_aliases": ("公司业务概要", "管理层讨论与分析", "经营情况讨论与分析"),
        "keywords": ("客户", "供应商", "采购", "销售客户", "依赖"),
    },
    "development_strategy": {
        "preferred_sections": ("company_profile", "business_overview", "management_discussion"),
        "heading_aliases": ("公司简介", "公司业务概要", "管理层讨论与分析", "经营情况讨论与分析"),
        "keywords": ("发展战略", "经营计划", "未来发展", "战略目标", "发展规划"),
    },
}

TOPIC_LABELS: Final[dict[str, str]] = {
    "business_overview": "主营业务",
    "industry_position": "行业地位",
    "market_share_disclosure": "市场份额披露",
    "competitive_advantage": "竞争优势",
    "technology_advantage": "技术优势",
    "research_and_development": "研发情况",
    "growth_drivers": "增长驱动因素",
    "management_explanation": "管理层解释",
    "business_risks": "经营风险",
    "customer_supplier_dependency": "客户与供应商依赖",
    "development_strategy": "发展战略",
}

COMPREHENSIVE_TOPICS: Final[tuple[str, ...]] = tuple(REPORT_TOPIC_CATALOG)
