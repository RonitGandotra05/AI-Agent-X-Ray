"""
Ingest routes - Receive pipeline run data
"""

from flask import Blueprint, request, jsonify
from ..models import db, Pipeline, Run, Step
from ..agents.analyzer import XRayAnalyzer

ingest_bp = Blueprint('ingest', __name__)


@ingest_bp.route('/api/ingest', methods=['POST'])
def ingest_run():
    """
    Receive a pipeline run and optionally trigger analysis.
    
    Request body:
    {
        "pipeline_name": "competitor_selection",
        "metadata": {"product_id": "123"},
        "steps": [
            {"name": "keyword_gen", "order": 1, "inputs": {...}, "outputs": {...}},
            ...
        ],
        "analyze": true  // optional, default true
    }
    """
    data = request.get_json()
    
    if not data:
        return jsonify({"error": "No JSON data provided"}), 400
    
    pipeline_name = data.get('pipeline_name')
    if not pipeline_name:
        return jsonify({"error": "pipeline_name is required"}), 400
    
    steps_data = data.get('steps', [])
    if not steps_data:
        return jsonify({"error": "At least one step is required"}), 400
    
    try:
        # Get or create pipeline
        pipeline = Pipeline.query.filter_by(name=pipeline_name).first()
        if not pipeline:
            pipeline = Pipeline(name=pipeline_name)
            db.session.add(pipeline)
            db.session.flush()
        
        # Create run
        run = Run(
            pipeline_id=pipeline.id,
            status='received',
            run_metadata=data.get('metadata', {})
        )
        db.session.add(run)
        db.session.flush()
        
        # Create steps
        for step_data in steps_data:
            step = Step(
                run_id=run.id,
                step_name=step_data.get('name', 'unknown'),
                step_order=step_data.get('order', 0),
                inputs=step_data.get('inputs', {}),
                outputs=step_data.get('outputs', {})
            )
            db.session.add(step)
        
        db.session.commit()
        
        # Trigger analysis if requested (default: True)
        should_analyze = data.get('analyze', True)
        analysis_result = None
        
        if should_analyze:
            try:
                analyzer = XRayAnalyzer()
                run_dict = run.to_dict(include_steps=True)
                analysis_result = analyzer.analyze_run(run_dict)
                
                # Save analysis result
                run.analysis_result = analysis_result
                run.status = 'analyzed'
                db.session.commit()
            except Exception as e:
                run.status = 'analysis_failed'
                run.analysis_result = {"error": str(e)}
                db.session.commit()
        else:
            run.status = 'stored'
            db.session.commit()
        
        return jsonify({
            "success": True,
            "run_id": run.id,
            "status": run.status,
            "analysis": analysis_result
        }), 201
        
    except Exception as e:
        db.session.rollback()
        return jsonify({"error": str(e)}), 500


@ingest_bp.route('/api/ingest/batch', methods=['POST'])
def ingest_batch():
    """Ingest multiple runs at once"""
    data = request.get_json()
    
    if not data or not isinstance(data.get('runs'), list):
        return jsonify({"error": "Expected {runs: [...]}"}), 400
    
    results = []
    for run_data in data['runs']:
        # Reuse single ingest logic
        with ingest_bp.test_request_context(
            '/api/ingest',
            method='POST',
            json=run_data
        ):
            # This is a simplified approach - in production, refactor to share logic
            pass
    
    return jsonify({"message": "Batch ingest not fully implemented yet"}), 501
