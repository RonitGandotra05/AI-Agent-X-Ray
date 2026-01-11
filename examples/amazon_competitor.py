"""
Example: Amazon Competitor Selection Pipeline with X-Ray SDK

This demonstrates how to use the X-Ray SDK to debug a multi-step
competitor selection pipeline.
"""

from dotenv import load_dotenv


import sys
import os

load_dotenv()

sys.path.insert(0, '.')

"""Demo: competitor selection pipeline with multiple steps."""

from xray_sdk import XRayClient, XRayRun, XRayStep


def main():
    # Simulate a pipeline execution with a bug in step 1
    
    # Create a new run
    run = XRayRun(
        pipeline_name="competitor_selection",
        description="E-commerce competitor selection pipeline that finds similar products on Amazon by generating keywords, searching, filtering, and ranking candidates.",
        metadata={
            "product_id": "ASIN123456",
            "product_title": "Premium Phone Case for iPhone 15",
            "category": "Cell Phone Accessories"
        },
        sample_size=20
    )
    
    # Step 1: Keyword Generation (HAS A BUG - generates "laptop cover")
    run.add_step(XRayStep(
        name="keyword_generation",
        order=1,
        description="LLM step - generates search keywords from the product title and category to find similar competitor products.",
        inputs={
            "product_title": "Premium Phone Case for iPhone 15",
            "category": "Cell Phone Accessories"
        },
        outputs={
            "keywords": ["phone case", "iphone 15 case", "laptop cover", "protective case"],
            "reasoning": "Generated keywords from title. Added 'laptop cover' as it's also a protective accessory."
        }
    ))
    
    # Step 2: Search API - Now with 500 candidates to test summarization!
    # Generate 500 candidates with detailed data (~100K chars, will be summarized to 100)
    all_candidates = []
    for i in range(500):
        # Mix of phone cases and laptop items (to show the bug)
        if i % 3 == 0:
            all_candidates.append({
                "asin": f"B{i:04d}",
                "title": f"Laptop Sleeve {i} inch Premium Quality",
                "category": "Laptop Accessories",
                "price": 20.0 + (i * 0.1),
                "rating": 4.0 + (i % 10) * 0.1,
                "reviews": 100 + i,
                "description": "High quality laptop protection sleeve with padding"
            })
        else:
            all_candidates.append({
                "asin": f"B{i:04d}",
                "title": f"iPhone 15 Case Model {i}",
                "category": "Phone Cases",
                "price": 15.0 + (i * 0.05),
                "rating": 4.2 + (i % 8) * 0.1,
                "reviews": 200 + i,
                "description": "Premium phone case with shock absorption"
            })
    
    print(f"\n📊 Step 2 has {len(all_candidates)} candidates (~{len(str(all_candidates))} chars)")
    
    run.add_step(XRayStep(
        name="search",
        order=2,
        description="API call step - searches Amazon catalog using the generated keywords to retrieve candidate products.",
        inputs={
            "keywords": ["phone case", "iphone 15 case", "laptop cover", "protective case"]
        },
        outputs={
            "candidates": all_candidates  # 500 items - will be auto-summarized to 100!
        }
    ))
    
    # Step 3: Filter
    run.add_step(XRayStep(
        name="filter",
        order=3,
        description="Data transformation step - filters candidates by price range, rating, and category to narrow down relevant products.",
        inputs={
            "candidates_count": 250,
            "filters": {
                "price_range": [10, 50],
                "min_rating": 4.0,
                "category_match": False  # Bug: not enforcing category match!
            }
        },
        outputs={
            "filtered_count": 45,
            "filtered_sample": [
                {"asin": "B001", "title": "iPhone 15 Pro Case", "score": 0.92},
                {"asin": "B002", "title": "Laptop Sleeve 15 inch", "score": 0.88},  # Wrong category!
                {"asin": "B003", "title": "iPhone 15 Clear Case", "score": 0.85}
            ]
        }
    ))
    
    # Step 4: Rank & Select
    run.add_step(XRayStep(
        name="rank_and_select",
        order=4,
        description="Scoring step - ranks filtered candidates by relevance, price similarity, and rating to select the best competitor match.",
        inputs={
            "filtered_candidates": 45,
            "ranking_criteria": ["relevance", "price_similarity", "rating"]
        },
        outputs={
            "selected": {
                "asin": "B002",
                "title": "Laptop Sleeve 15 inch",  # WRONG! Selected laptop instead of phone case
                "category": "Laptop Accessories",
                "price": 24.99,
                "relevance_score": 0.88
            },
            "reasoning": "Selected based on highest combined score for relevance and price match."
        }
    ))
    
    print("=" * 60)
    print("X-Ray SDK Demo: Amazon Competitor Selection")
    print("=" * 60)
    print(f"\nPipeline: {run.pipeline_name}")
    print(f"Steps: {len(run.steps)}")
    print("\nStep Summary:")
    for step in run.steps:
        print(f"  {step.order}. {step.name}")
    
    # Send to X-Ray API for analysis
    print("\n" + "=" * 60)
    print("Sending to X-Ray API for analysis...")
    print("=" * 60)
    
    client = XRayClient(api_url="https://ai-agent-x-ray.onrender.com", api_key=os.getenv("XRAY_API_KEY"))
    result = client.send(run)
    
    print("\nAPI Response:")
    import json
    print(json.dumps(result, indent=2, default=str))
    
    # If analysis was successful, show the faulty step
    if result.get('analysis'):
        analysis = result['analysis']
        print("\n" + "=" * 60)
        print("ANALYSIS RESULT")
        print("=" * 60)
        if analysis.get('faulty_step'):
            print(f"\n❌ Faulty Step: {analysis['faulty_step']} (Step {analysis.get('faulty_step_order', '?')})")
            print(f"\n📝 Reason: {analysis.get('reason', 'N/A')}")
            print(f"\n💡 Suggestion: {analysis.get('suggestion', 'N/A')}")
        else:
            print("\n✅ No issues detected in the pipeline.")


if __name__ == "__main__":
    main()
