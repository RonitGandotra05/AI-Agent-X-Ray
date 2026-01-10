"""Scenario: large outputs to exercise summarization + config inputs."""

from xray_sdk import XRayClient, XRayRun, XRayStep


def main() -> None:
    run = XRayRun("scenario_large_payload", metadata={"case": "large_payload"}, sample_size=50)
    
    # Generate 3000 candidates with detailed data (~800K+ chars total, will be summarized)
    candidates = [
        {
            "id": f"B{i:04d}",
            "title": f"Premium Phone Case Model {i} - Ultra Slim Design with Maximum Protection",
            "description": f"High-quality protective case with shock absorption, anti-scratch coating, and precise cutouts for all ports and buttons. Compatible with wireless charging. Features military-grade drop protection and a lifetime warranty.",
            "rating": 4.0 + (i % 10) / 10,
            "price": 15.99 + (i % 20),
            "reviews_count": 100 + i * 5,
            "seller": f"Seller_{i % 50}",
            "in_stock": i % 3 != 0,
            "category": "Phone Accessories",
            "brand": f"Brand_{i % 30}",
            "color": ["Black", "White", "Blue", "Red", "Green"][i % 5],
            "material": ["Silicone", "Leather", "Plastic", "Carbon Fiber"][i % 4]
        }
        for i in range(1, 3001)  # 3000 items
    ]
    
    print(f"📊 Generated {len(candidates)} candidates (~{len(str(candidates))} chars)")
    print("   (Payload exceeds 80K limit - check API logs to see summarization in action)")

    run.add_step(XRayStep(
        name="search",
        order=1,
        inputs={"keywords": ["phone case", "iphone 15 case"]},
        outputs={"candidates": candidates},
        description="Search the catalog and return candidate items."
    ))
    run.add_step(XRayStep(
        name="filter",
        order=2,
        inputs={"min_rating": 4.5},
        outputs={"filtered_count": 120, "filtered_sample": ["B0001", "B0002"]},
        description="Filter candidates by minimum rating.",
        metrics={"elimination_rate": 0.4}
    ))

    client = XRayClient("http://localhost:5000")
    result = client.send(run)
    print(result)


if __name__ == "__main__":
    main()
