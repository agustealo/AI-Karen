# Intelligent Search Plugin

A unified plugin providing multiple search modes for web search operations.

## Modes

### general
General purpose web search for answering broad questions. Suitable for most common queries.

**Default settings:**
- `max_urls`: 5
- `depth`: 1
- `freshness_bias`: 0.3
- `query_strategy`: "broad"
- `prefer_official_sources`: false
- `allow_forum_results`: true

### news
News-focused search for recent events and trending topics.

**Default settings:**
- `max_urls`: 8
- `depth`: 1
- `freshness_bias`: 0.8
- `query_strategy`: "news_biased"
- `prefer_recent`: true
- `prefer_official_sources`: true
- `prefer_news_publishers`: true

### docs
Documentation search for technical documentation, API references, and guides.

**Default settings:**
- `max_urls`: 6
- `depth`: 2
- `freshness_bias`: 0.4
- `query_strategy`: "official_docs_biased"
- `prefer_official_sources`: true
- `prefer_api_reference`: true
- `prefer_changelogs`: true
- `allow_forum_results`: false

**Additional fields:**
- `docs_hints.product`: Product/library name
- `docs_hints.version`: Specific version to target
- `docs_hints.language`: Programming language
- `docs_hints.target_doc_types`: List of doc types (e.g., ["api", "guide"])

### deep_research
In-depth research for complex topics requiring multiple sources and deeper analysis.

**Default settings:**
- `max_urls`: 10
- `depth`: 3
- `freshness_bias`: 0.5
- `query_strategy`: "research_biased"
- `prefer_official_sources`: true
- `prefer_academic_sources`: true
- `allow_forum_results`: false

### structured_extract
Structured data extraction with schema-based or instruction-based extraction.

**Default settings:**
- `max_urls`: 5
- `depth`: 1
- `query_strategy`: "targeted_extract"
- `extraction_preference`: "schema_first"
- `allow_llm_fallback`: true

**Additional fields:**
- `extraction.type`: "schema" | "css" | "xpath" | "instruction" | "llm"
- `extraction.schema`: JSON schema for structured output
- `extraction.instruction`: Natural language extraction instructions
- `extraction.target_fields`: List of fields to extract
- `extraction.target_selectors`: CSS/XPath selectors

### weather
Weather information queries.

**Default settings:**
- `units`: "auto" (metric or imperial based on location)
- `query_strategy`: "location_first"
- `include_current`: true
- `include_hourly`: false
- `include_daily`: false
- `include_alerts`: true
- `max_forecast_days`: 5

**Additional fields:**
- `location.name`: City or place name
- `location.latitude`: Latitude coordinate
- `location.longitude`: Longitude coordinate
- `time_policy.requested_date`: Specific date for weather
- `time_policy.requested_time`: Specific time for weather

### stock_market
Stock market and financial news search.

**Default settings:**
- `max_urls`: 8
- `depth`: 1
- `freshness_bias`: 0.9
- `query_strategy`: "market_news_biased"
- `prefer_recent`: true
- `prefer_official_sources`: true
- `prefer_financial_sources`: true
- `allow_forum_results`: false

**Additional fields:**
- `market_profile.ticker`: Stock ticker symbol
- `market_profile.company_name`: Company name
- `market_profile.exchange`: Exchange name
- `market_profile.sector`: Industry sector
- `market_profile.include_price_action`: Include price data
- `market_profile.include_company_news`: Include company news
- `market_profile.include_earnings`: Include earnings reports
- `market_profile.include_analyst_sentiment`: Include analyst ratings

## Usage

### Via extension registry
```python
result = await registry.execute_hook(
    hook_point=HookPoint.WEB_SEARCH,
    context={"query": "your query", "mode": "general"}
)
```

### Direct invocation
```python
from ai_karen_engine.extensions.plugins.web_search.handler import WebSearchDispatcher

dispatcher = WebSearchDispatcher(manifest, context)
await dispatcher.initialize()
result = await dispatcher.run({"query": "your query", "mode": "news"})
```

## Mode Selection

Mode is resolved using the following fallback chain:
1. `params["mode"]` - Explicit mode parameter
2. `params["context"]["mode"]` - Mode in context
3. Manifest default mode
4. "general" - Default fallback

## Configuration

The plugin supports multiple search providers with automatic fallback logic.

### Providers

1.  **DuckDuckGo (Free)**: Built-in scraper. No configuration needed.
2.  **Brave Search (Free)**: Built-in scraper. No configuration needed.
3.  **Mojeek (Free)**: Built-in reliable alternative scraper. No configuration needed.
4.  **SearxNG (Free)**: Built-in rotation of 12+ public instances. No configuration needed.
5.  **Wikipedia (Free)**: Built-in reliable knowledge search. No configuration needed.
6.  **Tavily (Premium)**: Highly accurate AI-focused search. Requires API key.
7.  **Brave Search (Premium)**: Official high-performance API. Requires API key.
8.  **Google Custom Search (Premium)**: Official Google results. Requires API key and CX ID.

### Setting API Keys

Configure the following settings in your `.env` or app settings:

```env
# Tavily Search
WEB_SEARCH_TAVILY_API_KEY=your_key_here

# Brave Search
WEB_SEARCH_BRAVE_API_KEY=your_key_here

# Google Custom Search
WEB_SEARCH_GOOGLE_API_KEY=your_key_here
WEB_SEARCH_GOOGLE_CX_ID=your_cx_id_here
```

### Common Parameters

All modes support:
- `query`: The search query (required)
- `max_urls`: Maximum number of URLs to retrieve
- `depth`: Search depth (number of hops)
- `freshness_bias`: Bias toward recent results (0.0 to 1.0)
- `allowed_domains`: List of allowed domains
- `blocked_domains`: List of blocked domains
- `time_range`: Time range filter (e.g., "d", "w", "m", "y")
- `published_after`: Date threshold for results
- `published_before`: Date threshold for results
