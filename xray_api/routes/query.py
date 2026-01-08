"""
Query routes - Retrieve and analyze pipeline runs
"""

from flask import Blueprint, request, jsonify
from ..models import db, Pipeline, Run, Step
from ..agents.analyzer import XRayAnalyzer

query_bp = Blueprint('query', __name__)


@query_bp.route('/api/pipelines', methods=['GET'])
def list_pipelines():
    """List all pipelines"""
    pipelines = Pipeline.query.order_by(Pipeline.created_at.desc()).all()
    return jsonify({
        "pipelines": [p.to_dict() for p in pipelines]
    })


@query_bp.route('/api/runs', methods=['GET'])
def list_runs():
    """
    List runs with optional filters.
    
    Query params:
    - pipeline: Filter by pipeline name
    - status: Filter by status
    - limit: Max results (default 50)
    """
    query = Run.query
    
    pipeline_name = request.args.get('pipeline')
    if pipeline_name:
        pipeline = Pipeline.query.filter_by(name=pipeline_name).first()
        if pipeline:
            query = query.filter_by(pipeline_id=pipeline.id)
        else:
            return jsonify({"runs": []})
    
    status = request.args.get('status')
    if status:
        query = query.filter_by(status=status)
    
    limit = request.args.get('limit', 50, type=int)
    runs = query.order_by(Run.created_at.desc()).limit(limit).all()
    
    return jsonify({
        "runs": [r.to_dict() for r in runs]
    })


@query_bp.route('/api/runs/<run_id>', methods=['GET'])
def get_run(run_id):
    """Get a single run with all its steps"""
    run = Run.query.get(run_id)
    if not run:
        return jsonify({"error": "Run not found"}), 404
    
    return jsonify(run.to_dict(include_steps=True))


@query_bp.route('/api/runs/<run_id>/analysis', methods=['GET'])
def get_analysis(run_id):
    """Get just the analysis result for a run"""
    run = Run.query.get(run_id)
    if not run:
        return jsonify({"error": "Run not found"}), 404
    
    return jsonify({
        "run_id": run.id,
        "status": run.status,
        "analysis": run.analysis_result
    })


@query_bp.route('/api/analyze/<run_id>', methods=['POST'])
def trigger_analysis(run_id):
    """Trigger (re-)analysis for a run"""
    run = Run.query.get(run_id)
    if not run:
        return jsonify({"error": "Run not found"}), 404
    
    try:
        analyzer = XRayAnalyzer()
        run_dict = run.to_dict(include_steps=True)
        analysis_result = analyzer.analyze_run(run_dict)
        
        run.analysis_result = analysis_result
        run.status = 'analyzed'
        db.session.commit()
        
        return jsonify({
            "success": True,
            "run_id": run.id,
            "analysis": analysis_result
        })
    except Exception as e:
        return jsonify({"error": str(e)}), 500


@query_bp.route('/api/search/steps', methods=['GET'])
def search_steps():
    """
    Search steps across all runs.
    
    Query params:
    - step_name: Filter by step name
    - pipeline: Filter by pipeline name
    """
    query = Step.query
    
    step_name = request.args.get('step_name')
    if step_name:
        query = query.filter(Step.step_name.ilike(f'%{step_name}%'))
    
    pipeline_name = request.args.get('pipeline')
    if pipeline_name:
        pipeline = Pipeline.query.filter_by(name=pipeline_name).first()
        if pipeline:
            run_ids = [r.id for r in Run.query.filter_by(pipeline_id=pipeline.id).all()]
            query = query.filter(Step.run_id.in_(run_ids))
    
    limit = request.args.get('limit', 50, type=int)
    steps = query.order_by(Step.created_at.desc()).limit(limit).all()
    
    return jsonify({
        "steps": [s.to_dict() for s in steps]
    })
