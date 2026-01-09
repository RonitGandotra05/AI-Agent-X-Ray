"""Minimal usage example: build a simple 4-step run and send for analysis."""

from xray_sdk import XRayClient, XRayRun, XRayStep

run = XRayRun("my_pipeline", metadata={"ctx": "demo"}, sample_size=20)
run.add_step(XRayStep("keyword_generation", 1, inputs={"product_title": "Premium Phone Case for iPhone 15", "category": "Cell Phone Accessories"}, outputs={"keywords": ["phone case", "iphone 15 case", "protective case"]}, description="Generate search keywords from the product title."))
run.add_step(XRayStep("search", 2, inputs={"keywords": ["phone case", "iphone 15 case", "protective case"]}, outputs={"candidates_count": 100, "candidates": ["B001", "B002", "B003"]}, description="Search the catalog for items matching the keywords."))
run.add_step(XRayStep("filter", 3, inputs={"candidates_count": 100, "filters": {"price_range": [10, 50], "min_rating": 4.0}}, outputs={"filtered_count": 45, "filtered_sample": ["B001", "B003"]}, description="Filter candidates by price and rating.", reasons={"dropped_items": [{"id": "B002", "reason": "price too high"}]}, metrics={"elimination_rate": 0.55}))
run.add_step(XRayStep("rank_and_select", 4, inputs={"filtered_count": 45, "filtered_sample": ["B001", "B003"]}, outputs={"selected": ["B001"]}, description="Rank remaining items and select the best match."))

client = XRayClient("http://localhost:5000")
result = client.send(run)  # triggers /api/ingest and analysis
if result.get("spooled"):
    print(f"spooled_run={result.get('spool_path')}")
else:
    flush_result = client.flush_spool()
    if flush_result.get("flushed"):
        print(f"flushed_spool={flush_result}")
print(result["analysis"])
